#!/usr/bin/env python3
"""
향상된 고성능 파일 전송 프로그램
- 진행률 표시 및 성능 모니터링
- 멀티스레드 압축/해제
- 동적 대역폭 조절
- 상세한 에러 리포팅
"""

import asyncio
import json
import logging
import os
import struct
import time
import threading
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Callable
import argparse
import signal
import sys
from queue import Queue
import multiprocessing

try:
    import aiofiles
    import xxhash
    import zstandard as zstd
    from tqdm import tqdm
    import psutil
except ImportError as e:
    print(f"필수 패키지가 설치되지 않았습니다: {e}")
    print("pip install -r requirements.txt 를 실행해주세요.")
    sys.exit(1)


# 성능 최적화 상수
CHUNK_SIZE = 2 * 1024 * 1024  # 2MB chunks for better throughput
COMPRESSION_LEVEL = 3
MAX_RETRIES = 5
TIMEOUT = 60
BUFFER_SIZE = 128 * 1024  # 128KB buffer
MAX_CONCURRENT_TRANSFERS = min(multiprocessing.cpu_count() * 2, 16)
PROGRESS_UPDATE_INTERVAL = 0.1  # 100ms


@dataclass
class TransferStats:
    """전송 통계 정보"""
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    total_bytes: int = 0
    transferred_bytes: int = 0
    start_time: float = 0
    current_speed: float = 0  # bytes/sec
    avg_speed: float = 0
    eta: float = 0  # estimated time to completion
    compression_ratio: float = 0
    network_utilization: float = 0
    cpu_usage: float = 0
    
    def get_progress_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.transferred_bytes / self.total_bytes) * 100
    
    def get_elapsed_time(self) -> float:
        if self.start_time == 0:
            return 0.0
        return time.time() - self.start_time
    
    def update_speed(self, bytes_transferred: int, elapsed: float):
        if elapsed > 0:
            self.current_speed = bytes_transferred / elapsed
            total_elapsed = self.get_elapsed_time()
            if total_elapsed > 0:
                self.avg_speed = self.transferred_bytes / total_elapsed
                remaining_bytes = self.total_bytes - self.transferred_bytes
                if self.avg_speed > 0:
                    self.eta = remaining_bytes / self.avg_speed


class PerformanceMonitor:
    """성능 모니터링 클래스"""
    
    def __init__(self, update_interval: float = 1.0):
        self.update_interval = update_interval
        self.running = False
        self.stats = TransferStats()
        self.callbacks: List[Callable[[TransferStats], None]] = []
        self._monitor_task = None
        
    def add_callback(self, callback: Callable[[TransferStats], None]):
        """성능 업데이트 콜백을 추가합니다."""
        self.callbacks.append(callback)
        
    def start_monitoring(self):
        """모니터링을 시작합니다."""
        self.running = True
        self.stats.start_time = time.time()
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
    async def stop_monitoring(self):
        """모니터링을 중지합니다."""
        self.running = False
        if self._monitor_task:
            await self._monitor_task
            
    async def _monitor_loop(self):
        """성능 모니터링 루프"""
        last_bytes = 0
        last_time = time.time()
        
        while self.running:
            await asyncio.sleep(self.update_interval)
            
            current_time = time.time()
            elapsed = current_time - last_time
            bytes_diff = self.stats.transferred_bytes - last_bytes
            
            if elapsed > 0:
                self.stats.update_speed(bytes_diff, elapsed)
                
            # 시스템 리소스 사용량 업데이트
            self.stats.cpu_usage = psutil.cpu_percent(interval=None)
            
            # 네트워크 사용량 계산 (근사치)
            net_io = psutil.net_io_counters()
            if hasattr(self, '_last_net_bytes'):
                net_diff = (net_io.bytes_sent + net_io.bytes_recv) - self._last_net_bytes
                self.stats.network_utilization = net_diff / elapsed if elapsed > 0 else 0
            self._last_net_bytes = net_io.bytes_sent + net_io.bytes_recv
            
            # 콜백 호출
            for callback in self.callbacks:
                try:
                    callback(self.stats)
                except Exception as e:
                    logging.error(f"성능 모니터 콜백 오류: {e}")
                    
            last_bytes = self.stats.transferred_bytes
            last_time = current_time


class CompressedDataHandler:
    """압축 데이터 처리 클래스"""
    
    def __init__(self, compression_level: int = COMPRESSION_LEVEL):
        self.compression_level = compression_level
        self.executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TRANSFERS)
        
    def compress_chunk(self, data: bytes) -> bytes:
        """청크를 압축합니다."""
        compressor = zstd.ZstdCompressor(level=self.compression_level)
        return compressor.compress(data)
    
    def decompress_chunk(self, data: bytes) -> bytes:
        """청크를 압축해제합니다."""
        decompressor = zstd.ZstdDecompressor()
        return decompressor.decompress(data)
    
    async def compress_async(self, data: bytes) -> bytes:
        """비동기로 압축합니다."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.compress_chunk, data)
    
    async def decompress_async(self, data: bytes) -> bytes:
        """비동기로 압축해제합니다."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.decompress_chunk, data)
    
    def shutdown(self):
        """스레드 풀을 종료합니다."""
        self.executor.shutdown(wait=True)


class ProgressDisplay:
    """진행률 표시 클래스"""
    
    def __init__(self):
        self.pbar = None
        self.last_update = 0
        
    def create_progress_bar(self, total_bytes: int, desc: str = "전송 중"):
        """진행률 바를 생성합니다."""
        self.pbar = tqdm(
            total=total_bytes,
            unit='B',
            unit_scale=True,
            unit_divisor=1024,
            desc=desc,
            miniters=1,
            mininterval=PROGRESS_UPDATE_INTERVAL
        )
        
    def update_progress(self, stats: TransferStats):
        """진행률을 업데이트합니다."""
        if not self.pbar:
            return
            
        current_time = time.time()
        if current_time - self.last_update < PROGRESS_UPDATE_INTERVAL:
            return
            
        # 진행률 업데이트
        delta = stats.transferred_bytes - self.pbar.n
        if delta > 0:
            self.pbar.update(delta)
            
        # 상태 정보 업데이트
        speed_mb = stats.current_speed / (1024 * 1024) if stats.current_speed > 0 else 0
        eta_str = f"{stats.eta:.0f}s" if stats.eta > 0 else "∞"
        
        self.pbar.set_postfix({
            'Speed': f'{speed_mb:.1f}MB/s',
            'Files': f'{stats.completed_files}/{stats.total_files}',
            'CPU': f'{stats.cpu_usage:.1f}%',
            'ETA': eta_str
        })
        
        self.last_update = current_time
        
    def close(self):
        """진행률 바를 닫습니다."""
        if self.pbar:
            self.pbar.close()


class EnhancedFileTransferProtocol:
    """향상된 파일 전송 프로토콜"""
    
    def __init__(self, compression_level: int = COMPRESSION_LEVEL):
        self.compression_handler = CompressedDataHandler(compression_level)
        self.logger = logging.getLogger(__name__)
        
    def calculate_checksum(self, data: bytes) -> str:
        """빠른 체크섬 계산"""
        return xxhash.xxh64(data).hexdigest()
    
    async def send_message(self, writer: asyncio.StreamWriter, message: Dict) -> None:
        """메시지를 전송합니다."""
        data = json.dumps(message, ensure_ascii=False).encode('utf-8')
        length = len(data)
        
        # 메시지 길이와 데이터를 한 번에 전송
        writer.write(struct.pack('!I', length) + data)
        await writer.drain()
    
    async def receive_message(self, reader: asyncio.StreamReader) -> Optional[Dict]:
        """메시지를 수신합니다."""
        try:
            length_data = await asyncio.wait_for(reader.readexactly(4), timeout=TIMEOUT)
            length = struct.unpack('!I', length_data)[0]
            
            if length > 10 * 1024 * 1024:  # 10MB 제한
                raise ValueError(f"메시지가 너무 큽니다: {length} bytes")
            
            data = await asyncio.wait_for(reader.readexactly(length), timeout=TIMEOUT)
            return json.loads(data.decode('utf-8'))
            
        except (asyncio.IncompleteReadError, json.JSONDecodeError, asyncio.TimeoutError) as e:
            self.logger.error(f"메시지 수신 오류: {e}")
            return None
    
    async def send_file_chunk(self, writer: asyncio.StreamWriter, data: bytes, 
                            compress: bool = True) -> Tuple[int, str]:
        """파일 청크를 전송합니다."""
        if compress:
            compressed_data = await self.compression_handler.compress_async(data)
            checksum = self.calculate_checksum(data)  # 원본 데이터의 체크섬
        else:
            compressed_data = data
            checksum = self.calculate_checksum(data)
        
        # 청크 헤더: 압축된 크기, 원본 크기, 체크섬
        header = {
            'compressed_size': len(compressed_data),
            'original_size': len(data),
            'checksum': checksum,
            'compressed': compress
        }
        
        await self.send_message(writer, header)
        writer.write(compressed_data)
        await writer.drain()
        
        return len(compressed_data), checksum
    
    async def receive_file_chunk(self, reader: asyncio.StreamReader) -> Optional[bytes]:
        """파일 청크를 수신합니다."""
        try:
            header = await self.receive_message(reader)
            if not header:
                return None
            
            compressed_size = header['compressed_size']
            original_size = header['original_size']
            expected_checksum = header['checksum']
            is_compressed = header.get('compressed', True)
            
            # 청크 데이터 수신
            chunk_data = await asyncio.wait_for(
                reader.readexactly(compressed_size), 
                timeout=TIMEOUT
            )
            
            # 압축 해제
            if is_compressed:
                original_data = await self.compression_handler.decompress_async(chunk_data)
            else:
                original_data = chunk_data
            
            # 크기 및 체크섬 검증
            if len(original_data) != original_size:
                raise ValueError("청크 크기 불일치")
            
            actual_checksum = self.calculate_checksum(original_data)
            if actual_checksum != expected_checksum:
                raise ValueError("청크 체크섬 불일치")
            
            return original_data
            
        except Exception as e:
            self.logger.error(f"청크 수신 오류: {e}")
            return None
    
    def cleanup(self):
        """리소스를 정리합니다."""
        self.compression_handler.shutdown()


class EnhancedFileTransferServer:
    """향상된 파일 전송 서버"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8888):
        self.host = host
        self.port = port
        self.protocol = EnhancedFileTransferProtocol()
        self.logger = logging.getLogger(__name__)
        self.server = None
        self.running = False
        self.active_transfers = {}
        
    async def start(self):
        """서버를 시작합니다."""
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port,
            limit=BUFFER_SIZE
        )
        self.running = True
        
        addr = self.server.sockets[0].getsockname()
        self.logger.info(f"향상된 파일 전송 서버가 {addr}에서 시작되었습니다.")
        
        async with self.server:
            await self.server.serve_forever()
    
    async def stop(self):
        """서버를 중지합니다."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            
        # 활성 전송 정리
        for transfer_id in list(self.active_transfers.keys()):
            await self.cancel_transfer(transfer_id)
            
        self.protocol.cleanup()
        self.logger.info("서버가 중지되었습니다.")
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """클라이언트 연결을 처리합니다."""
        client_addr = writer.get_extra_info('peername')
        self.logger.info(f"클라이언트 연결: {client_addr}")
        
        try:
            while self.running:
                message = await self.protocol.receive_message(reader)
                if not message:
                    break
                
                command = message.get('command')
                
                if command == 'upload':
                    await self.handle_upload(reader, writer, message)
                elif command == 'download':
                    await self.handle_download(reader, writer, message)
                elif command == 'list':
                    await self.handle_list(writer, message)
                elif command == 'status':
                    await self.handle_status(writer, message)
                elif command == 'close':
                    break
                else:
                    await self.protocol.send_message(writer, {
                        'status': 'error',
                        'message': f'알 수 없는 명령: {command}'
                    })
                    
        except Exception as e:
            self.logger.error(f"클라이언트 처리 오류: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            self.logger.info(f"클라이언트 연결 종료: {client_addr}")
    
    async def handle_upload(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, message: Dict):
        """파일 업로드를 처리합니다."""
        try:
            target_path = message['path']
            file_size = message['size']
            num_chunks = message.get('chunks', 1)
            
            # 전송 ID 생성
            transfer_id = f"upload_{int(time.time())}_{hash(target_path)}"
            
            # 디렉토리 생성
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # 성공 응답 전송
            await self.protocol.send_message(writer, {
                'status': 'ready',
                'transfer_id': transfer_id
            })
            
            # 파일 수신 및 저장
            received_data = b''
            for chunk_idx in range(num_chunks):
                chunk_data = await self.protocol.receive_file_chunk(reader)
                if chunk_data is None:
                    raise ValueError(f"청크 {chunk_idx} 수신 실패")
                received_data += chunk_data
            
            # 파일 저장
            async with aiofiles.open(target_path, 'wb') as f:
                await f.write(received_data)
            
            # 최종 검증
            if len(received_data) != file_size:
                raise ValueError("파일 크기 불일치")
            
            await self.protocol.send_message(writer, {
                'status': 'success',
                'message': '파일 업로드 완료',
                'transferred_bytes': len(received_data)
            })
            
        except Exception as e:
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'업로드 오류: {e}'
            })
    
    async def handle_download(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, message: Dict):
        """파일 다운로드를 처리합니다."""
        try:
            file_path = message['path']
            
            if not os.path.exists(file_path):
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': '파일을 찾을 수 없습니다'
                })
                return
            
            file_size = os.path.getsize(file_path)
            num_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            # 파일 정보 전송
            await self.protocol.send_message(writer, {
                'status': 'ready',
                'size': file_size,
                'chunks': num_chunks
            })
            
            # 클라이언트 준비 확인
            response = await self.protocol.receive_message(reader)
            if not response or response.get('status') != 'ready':
                return
            
            # 파일 전송
            async with aiofiles.open(file_path, 'rb') as f:
                for chunk_idx in range(num_chunks):
                    chunk_data = await f.read(CHUNK_SIZE)
                    if not chunk_data:
                        break
                    
                    await self.protocol.send_file_chunk(writer, chunk_data)
            
            # 완료 확인
            response = await self.protocol.receive_message(reader)
            if response and response.get('status') == 'completed':
                self.logger.info(f"파일 다운로드 완료: {file_path}")
            
        except Exception as e:
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'다운로드 오류: {e}'
            })
    
    async def handle_list(self, writer: asyncio.StreamWriter, message: Dict):
        """파일 목록을 처리합니다."""
        try:
            directory = message.get('path', '.')
            if not os.path.exists(directory):
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': '디렉토리를 찾을 수 없습니다'
                })
                return
            
            files = []
            total_size = 0
            
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                try:
                    stat = os.stat(item_path)
                    is_dir = os.path.isdir(item_path)
                    
                    files.append({
                        'name': item,
                        'size': stat.st_size if not is_dir else 0,
                        'modified': stat.st_mtime,
                        'is_directory': is_dir,
                        'permissions': oct(stat.st_mode)[-3:]
                    })
                    
                    if not is_dir:
                        total_size += stat.st_size
                        
                except OSError as e:
                    self.logger.warning(f"파일 정보 조회 실패 {item}: {e}")
            
            await self.protocol.send_message(writer, {
                'status': 'success',
                'files': files,
                'total_size': total_size,
                'total_files': len([f for f in files if not f['is_directory']])
            })
            
        except Exception as e:
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'목록 조회 오류: {e}'
            })
    
    async def handle_status(self, writer: asyncio.StreamWriter, message: Dict):
        """서버 상태를 처리합니다."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            await self.protocol.send_message(writer, {
                'status': 'success',
                'server_info': {
                    'cpu_usage': cpu_percent,
                    'memory_usage': memory.percent,
                    'memory_available': memory.available,
                    'disk_usage': disk.percent,
                    'disk_free': disk.free,
                    'active_transfers': len(self.active_transfers),
                    'uptime': time.time() - (self.start_time if hasattr(self, 'start_time') else time.time())
                }
            })
            
        except Exception as e:
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'상태 조회 오류: {e}'
            })
    
    async def cancel_transfer(self, transfer_id: str):
        """전송을 취소합니다."""
        if transfer_id in self.active_transfers:
            # 전송 취소 로직 구현
            del self.active_transfers[transfer_id]


class EnhancedFileTransferClient:
    """향상된 파일 전송 클라이언트"""
    
    def __init__(self, host: str, port: int = 8888):
        self.host = host
        self.port = port
        self.protocol = EnhancedFileTransferProtocol()
        self.logger = logging.getLogger(__name__)
        self.reader = None
        self.writer = None
        self.monitor = PerformanceMonitor()
        self.progress_display = ProgressDisplay()
        
    async def connect(self) -> bool:
        """서버에 연결합니다."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=TIMEOUT
            )
            
            # TCP 최적화 설정
            sock = self.writer.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
            
            self.logger.info(f"서버에 연결되었습니다: {self.host}:{self.port}")
            return True
            
        except Exception as e:
            self.logger.error(f"서버 연결 실패: {e}")
            return False
    
    async def disconnect(self):
        """서버 연결을 끊습니다."""
        try:
            if self.writer:
                await self.protocol.send_message(self.writer, {'command': 'close'})
                self.writer.close()
                await self.writer.wait_closed()
        except Exception as e:
            self.logger.error(f"연결 종료 오류: {e}")
        finally:
            await self.monitor.stop_monitoring()
            self.progress_display.close()
            self.protocol.cleanup()
            self.logger.info("서버 연결을 종료했습니다.")
    
    async def upload_file(self, local_path: str, remote_path: str, retries: int = MAX_RETRIES) -> bool:
        """파일을 업로드합니다."""
        for attempt in range(retries + 1):
            try:
                if not os.path.exists(local_path):
                    self.logger.error(f"파일을 찾을 수 없습니다: {local_path}")
                    return False
                
                file_size = os.path.getsize(local_path)
                num_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
                
                # 진행률 모니터링 설정
                self.monitor.stats.total_bytes = file_size
                self.monitor.stats.total_files = 1
                self.progress_display.create_progress_bar(file_size, f"업로드: {os.path.basename(local_path)}")
                self.monitor.add_callback(self.progress_display.update_progress)
                self.monitor.start_monitoring()
                
                # 업로드 요청 전송
                await self.protocol.send_message(self.writer, {
                    'command': 'upload',
                    'path': remote_path,
                    'size': file_size,
                    'chunks': num_chunks
                })
                
                # 서버 준비 확인
                response = await self.protocol.receive_message(self.reader)
                if not response or response.get('status') != 'ready':
                    error_msg = response.get('message', '서버 응답 없음') if response else '응답 없음'
                    self.logger.error(f"업로드 준비 실패: {error_msg}")
                    continue
                
                # 파일 청크 전송
                transferred_bytes = 0
                async with aiofiles.open(local_path, 'rb') as f:
                    for chunk_idx in range(num_chunks):
                        chunk_data = await f.read(CHUNK_SIZE)
                        if not chunk_data:
                            break
                        
                        compressed_size, checksum = await self.protocol.send_file_chunk(
                            self.writer, chunk_data
                        )
                        
                        transferred_bytes += len(chunk_data)
                        self.monitor.stats.transferred_bytes = transferred_bytes
                
                # 완료 응답 수신
                response = await self.protocol.receive_message(self.reader)
                if response and response.get('status') == 'success':
                    self.monitor.stats.completed_files = 1
                    self.logger.info(f"파일 업로드 완료: {local_path} -> {remote_path}")
                    return True
                else:
                    error_msg = response.get('message', '알 수 없는 오류') if response else '응답 없음'
                    self.logger.error(f"업로드 실패: {error_msg}")
                    
            except Exception as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: {e}")
                if attempt < retries:
                    await asyncio.sleep(min(2 ** attempt, 10))  # 지수 백오프
                    
        return False
    
    async def download_file(self, remote_path: str, local_path: str, retries: int = MAX_RETRIES) -> bool:
        """파일을 다운로드합니다."""
        for attempt in range(retries + 1):
            try:
                # 다운로드 요청 전송
                await self.protocol.send_message(self.writer, {
                    'command': 'download',
                    'path': remote_path
                })
                
                # 파일 정보 수신
                response = await self.protocol.receive_message(self.reader)
                if not response or response.get('status') != 'ready':
                    error_msg = response.get('message', '알 수 없는 오류') if response else '응답 없음'
                    self.logger.error(f"다운로드 실패: {error_msg}")
                    continue
                
                file_size = response['size']
                num_chunks = response['chunks']
                
                # 진행률 모니터링 설정
                self.monitor.stats.total_bytes = file_size
                self.monitor.stats.total_files = 1
                self.progress_display.create_progress_bar(file_size, f"다운로드: {os.path.basename(remote_path)}")
                self.monitor.add_callback(self.progress_display.update_progress)
                self.monitor.start_monitoring()
                
                # 준비 완료 신호 전송
                await self.protocol.send_message(self.writer, {'status': 'ready'})
                
                # 디렉토리 생성
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                # 파일 수신 및 저장
                received_data = b''
                transferred_bytes = 0
                
                for chunk_idx in range(num_chunks):
                    chunk_data = await self.protocol.receive_file_chunk(self.reader)
                    if chunk_data is None:
                        raise ValueError(f"청크 {chunk_idx} 수신 실패")
                    
                    received_data += chunk_data
                    transferred_bytes += len(chunk_data)
                    self.monitor.stats.transferred_bytes = transferred_bytes
                
                # 파일 저장
                async with aiofiles.open(local_path, 'wb') as f:
                    await f.write(received_data)
                
                # 완료 신호 전송
                await self.protocol.send_message(self.writer, {'status': 'completed'})
                
                # 최종 검증
                if len(received_data) != file_size:
                    raise ValueError("파일 크기 불일치")
                
                self.monitor.stats.completed_files = 1
                self.logger.info(f"파일 다운로드 완료: {remote_path} -> {local_path}")
                return True
                
            except Exception as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: {e}")
                if attempt < retries:
                    await asyncio.sleep(min(2 ** attempt, 10))
                    
        return False
    
    async def transfer_directory(self, local_dir: str, remote_dir: str, upload: bool = True) -> bool:
        """디렉토리를 재귀적으로 전송합니다."""
        files_to_transfer = []
        total_size = 0
        
        # 전송할 파일 목록 수집
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_file = os.path.join(root, file)
                relative_path = os.path.relpath(local_file, local_dir)
                remote_file = os.path.join(remote_dir, relative_path).replace('\\', '/')
                
                try:
                    file_size = os.path.getsize(local_file)
                    files_to_transfer.append((local_file, remote_file, file_size))
                    total_size += file_size
                except OSError as e:
                    self.logger.warning(f"파일 크기 조회 실패 {local_file}: {e}")
        
        if not files_to_transfer:
            self.logger.info("전송할 파일이 없습니다.")
            return True
        
        # 전체 진행률 모니터링 설정
        self.monitor.stats.total_files = len(files_to_transfer)
        self.monitor.stats.total_bytes = total_size
        self.progress_display.create_progress_bar(total_size, f"디렉토리 {'업로드' if upload else '다운로드'}")
        self.monitor.add_callback(self.progress_display.update_progress)
        self.monitor.start_monitoring()
        
        success_count = 0
        
        # 파일 전송
        for local_file, remote_file, file_size in files_to_transfer:
            try:
                if upload:
                    success = await self.upload_file_single(local_file, remote_file, file_size)
                else:
                    success = await self.download_file_single(remote_file, local_file, file_size)
                
                if success:
                    success_count += 1
                    self.monitor.stats.completed_files += 1
                else:
                    self.monitor.stats.failed_files += 1
                    
            except Exception as e:
                self.logger.error(f"파일 전송 오류 {local_file}: {e}")
                self.monitor.stats.failed_files += 1
        
        success_rate = success_count / len(files_to_transfer) * 100
        self.logger.info(f"디렉토리 전송 완료: {success_count}/{len(files_to_transfer)} 파일 ({success_rate:.1f}%)")
        
        return success_count == len(files_to_transfer)
    
    async def upload_file_single(self, local_path: str, remote_path: str, file_size: int) -> bool:
        """단일 파일 업로드 (디렉토리 전송용)"""
        try:
            num_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            # 업로드 요청
            await self.protocol.send_message(self.writer, {
                'command': 'upload',
                'path': remote_path,
                'size': file_size,
                'chunks': num_chunks
            })
            
            # 서버 응답 확인
            response = await self.protocol.receive_message(self.reader)
            if not response or response.get('status') != 'ready':
                return False
            
            # 파일 전송
            async with aiofiles.open(local_path, 'rb') as f:
                for _ in range(num_chunks):
                    chunk_data = await f.read(CHUNK_SIZE)
                    if not chunk_data:
                        break
                    
                    await self.protocol.send_file_chunk(self.writer, chunk_data)
                    self.monitor.stats.transferred_bytes += len(chunk_data)
            
            # 완료 확인
            response = await self.protocol.receive_message(self.reader)
            return response and response.get('status') == 'success'
            
        except Exception as e:
            self.logger.error(f"파일 업로드 오류 {local_path}: {e}")
            return False
    
    async def download_file_single(self, remote_path: str, local_path: str, expected_size: int) -> bool:
        """단일 파일 다운로드 (디렉토리 전송용)"""
        try:
            # 다운로드 요청
            await self.protocol.send_message(self.writer, {
                'command': 'download',
                'path': remote_path
            })
            
            # 파일 정보 수신
            response = await self.protocol.receive_message(self.reader)
            if not response or response.get('status') != 'ready':
                return False
            
            file_size = response['size']
            num_chunks = response['chunks']
            
            # 준비 신호
            await self.protocol.send_message(self.writer, {'status': 'ready'})
            
            # 파일 수신
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            received_data = b''
            
            for _ in range(num_chunks):
                chunk_data = await self.protocol.receive_file_chunk(self.reader)
                if chunk_data is None:
                    return False
                
                received_data += chunk_data
                self.monitor.stats.transferred_bytes += len(chunk_data)
            
            # 파일 저장
            async with aiofiles.open(local_path, 'wb') as f:
                await f.write(received_data)
            
            # 완료 신호
            await self.protocol.send_message(self.writer, {'status': 'completed'})
            
            return len(received_data) == file_size
            
        except Exception as e:
            self.logger.error(f"파일 다운로드 오류 {remote_path}: {e}")
            return False


def setup_logging(level: str = 'INFO'):
    """로깅을 설정합니다."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('enhanced_transfer.log')
        ]
    )


async def run_enhanced_server(host: str, port: int):
    """향상된 서버를 실행합니다."""
    server = EnhancedFileTransferServer(host, port)
    
    def signal_handler(signum, frame):
        asyncio.create_task(server.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()


async def run_enhanced_client(host: str, port: int, command: str, local_path: str, remote_path: str):
    """향상된 클라이언트를 실행합니다."""
    client = EnhancedFileTransferClient(host, port)
    
    if not await client.connect():
        return False
    
    try:
        if command == 'upload':
            if os.path.isfile(local_path):
                return await client.upload_file(local_path, remote_path)
            elif os.path.isdir(local_path):
                return await client.transfer_directory(local_path, remote_path, upload=True)
        elif command == 'download':
            if local_path.endswith('/') or os.path.isdir(local_path):
                return await client.transfer_directory(local_path, remote_path, upload=False)
            else:
                return await client.download_file(remote_path, local_path)
                
    finally:
        await client.disconnect()
    
    return False


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='향상된 고성능 파일 전송 프로그램')
    parser.add_argument('--mode', choices=['server', 'client'], required=True,
                        help='실행 모드')
    parser.add_argument('--host', default='localhost',
                        help='서버 호스트 (기본값: localhost)')
    parser.add_argument('--port', type=int, default=8888,
                        help='서버 포트 (기본값: 8888)')
    parser.add_argument('--command', choices=['upload', 'download'],
                        help='클라이언트 명령')
    parser.add_argument('--local', help='로컬 파일/디렉토리 경로')
    parser.add_argument('--remote', help='원격 파일/디렉토리 경로')
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='로그 레벨')
    parser.add_argument('--compression-level', type=int, default=COMPRESSION_LEVEL,
                        help=f'압축 레벨 (1-22, 기본값: {COMPRESSION_LEVEL})')
    
    args = parser.parse_args()
    
    setup_logging(args.log_level)
    
    # 전역 압축 레벨 설정
    global COMPRESSION_LEVEL
    COMPRESSION_LEVEL = args.compression_level
    
    if args.mode == 'server':
        print(f"향상된 파일 전송 서버를 시작합니다: {args.host}:{args.port}")
        print(f"압축 레벨: {COMPRESSION_LEVEL}, 최대 동시 전송: {MAX_CONCURRENT_TRANSFERS}")
        asyncio.run(run_enhanced_server(args.host, args.port))
        
    elif args.mode == 'client':
        if not all([args.command, args.local, args.remote]):
            print("클라이언트 모드에서는 --command, --local, --remote 옵션이 필요합니다.")
            return
        
        print(f"향상된 파일 전송을 시작합니다: {args.command}")
        print(f"압축 레벨: {COMPRESSION_LEVEL}")
        
        success = asyncio.run(run_enhanced_client(
            args.host, args.port, args.command, args.local, args.remote
        ))
        
        if success:
            print("전송이 완료되었습니다.")
        else:
            print("전송 중 오류가 발생했습니다.")


if __name__ == '__main__':
    main() 