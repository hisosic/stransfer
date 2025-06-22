#!/usr/bin/env python3
"""
고성능 파일 전송 프로그램
- CPU 및 네트워크 대역폭 최대 활용
- 데이터 무결성 보장
- 실패 시 재시도 기능
- 패킷 손실 대응
"""

import asyncio
import hashlib
import json
import logging
import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import argparse
import socket
import signal
import sys
import psutil

try:
    import aiofiles
    import xxhash
    import zstandard as zstd
    from tqdm import tqdm
except ImportError as e:
    print(f"필수 패키지가 설치되지 않았습니다: {e}")
    print("pip install -r requirements.txt 를 실행해주세요.")
    sys.exit(1)


class PerformanceMonitor:
    """성능 모니터링 클래스"""
    
    def __init__(self, logger):
        self.logger = logger
        self.start_time = None
        self.monitoring = False
        self.stats = {
            'cpu_usage': [],
            'memory_usage': [],
            'network_io': [],
            'disk_io': []
        }
    
    def start_monitoring(self):
        """모니터링 시작"""
        self.start_time = time.time()
        self.monitoring = True
        self.stats = {
            'cpu_usage': [],
            'memory_usage': [],
            'network_io': [],
            'disk_io': []
        }
        
        # 백그라운드 모니터링 태스크 시작
        asyncio.create_task(self._monitor_performance())
    
    def stop_monitoring(self):
        """모니터링 중지"""
        self.monitoring = False
        elapsed = time.time() - self.start_time if self.start_time else 0
        self._print_performance_summary(elapsed)
    
    async def _monitor_performance(self):
        """성능 모니터링 루프"""
        initial_net_io = psutil.net_io_counters()
        initial_disk_io = psutil.disk_io_counters()
        
        while self.monitoring:
            try:
                # CPU 사용률
                cpu_percent = psutil.cpu_percent(interval=None)
                self.stats['cpu_usage'].append(cpu_percent)
                
                # 메모리 사용률
                memory = psutil.virtual_memory()
                self.stats['memory_usage'].append(memory.percent)
                
                # 네트워크 I/O
                net_io = psutil.net_io_counters()
                if initial_net_io:
                    net_speed = {
                        'bytes_sent': net_io.bytes_sent - initial_net_io.bytes_sent,
                        'bytes_recv': net_io.bytes_recv - initial_net_io.bytes_recv
                    }
                    self.stats['network_io'].append(net_speed)
                
                # 디스크 I/O
                disk_io = psutil.disk_io_counters()
                if initial_disk_io:
                    disk_speed = {
                        'read_bytes': disk_io.read_bytes - initial_disk_io.read_bytes,
                        'write_bytes': disk_io.write_bytes - initial_disk_io.write_bytes
                    }
                    self.stats['disk_io'].append(disk_speed)
                
                await asyncio.sleep(1)  # 1초마다 측정
                
            except Exception as e:
                self.logger.debug(f"성능 모니터링 오류: {e}")
                break
    
    def _print_performance_summary(self, elapsed_time: float):
        """성능 요약 출력"""
        if not self.stats['cpu_usage']:
            return
        
        # CPU 통계
        avg_cpu = sum(self.stats['cpu_usage']) / len(self.stats['cpu_usage'])
        max_cpu = max(self.stats['cpu_usage'])
        
        # 메모리 통계
        avg_memory = sum(self.stats['memory_usage']) / len(self.stats['memory_usage'])
        max_memory = max(self.stats['memory_usage'])
        
        # 네트워크 통계
        total_sent = 0
        total_recv = 0
        if self.stats['network_io']:
            last_net = self.stats['network_io'][-1]
            total_sent = last_net['bytes_sent']
            total_recv = last_net['bytes_recv']
        
        # 디스크 통계
        total_read = 0
        total_write = 0
        if self.stats['disk_io']:
            last_disk = self.stats['disk_io'][-1]
            total_read = last_disk['read_bytes']
            total_write = last_disk['write_bytes']
        
        self.logger.info("=== 성능 요약 ===")
        self.logger.info(f"실행 시간: {elapsed_time:.1f}초")
        self.logger.info(f"CPU 사용률: 평균 {avg_cpu:.1f}%, 최대 {max_cpu:.1f}%")
        self.logger.info(f"메모리 사용률: 평균 {avg_memory:.1f}%, 최대 {max_memory:.1f}%")
        self.logger.info(f"네트워크: 송신 {total_sent/(1024*1024):.1f}MB, 수신 {total_recv/(1024*1024):.1f}MB")
        self.logger.info(f"디스크: 읽기 {total_read/(1024*1024):.1f}MB, 쓰기 {total_write/(1024*1024):.1f}MB")
        
        if elapsed_time > 0:
            net_speed = (total_sent + total_recv) / (1024 * 1024) / elapsed_time
            disk_speed = (total_read + total_write) / (1024 * 1024) / elapsed_time
            self.logger.info(f"평균 네트워크 속도: {net_speed:.1f} MB/s")
            self.logger.info(f"평균 디스크 속도: {disk_speed:.1f} MB/s")


# 상수 정의
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks (더 큰 청크로 변경)
COMPRESSION_LEVEL = 1  # 빠른 압축 레벨로 변경
MAX_RETRIES = 3
TIMEOUT = 30
BUFFER_SIZE = 1024 * 1024  # 1MB 버퍼 (증가)
MAX_CONCURRENT_CHUNKS = 4  # 동시 처리할 청크 수
PIPELINE_SIZE = 8  # 파이프라인 크기


@dataclass
class FileInfo:
    """파일 정보 데이터 클래스"""
    path: str
    size: int
    checksum: str
    modified_time: float
    is_directory: bool = False


@dataclass
class TransferProgress:
    """전송 진행률 데이터 클래스"""
    total_files: int = 0
    transferred_files: int = 0
    total_bytes: int = 0
    transferred_bytes: int = 0
    current_file: str = ""
    start_time: float = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class FileTransferProtocol:
    """파일 전송 프로토콜 클래스"""
    
    def __init__(self, compression_level: int = COMPRESSION_LEVEL):
        self.compression_level = compression_level
        self.compressor = zstd.ZstdCompressor(level=compression_level)
        self.decompressor = zstd.ZstdDecompressor()
        self.logger = logging.getLogger(__name__)
        
    def calculate_checksum(self, data: bytes) -> str:
        """데이터의 체크섬을 계산합니다."""
        return xxhash.xxh64(data).hexdigest()
    
    def compress_data(self, data: bytes) -> bytes:
        """데이터를 압축합니다. (고성능을 위해 압축 비활성화)"""
        # 고성능 전송을 위해 압축 비활성화
        return data
    
    def decompress_data(self, data: bytes) -> bytes:
        """데이터를 압축해제합니다. (고성능을 위해 압축 비활성화)"""
        # 고성능 전송을 위해 압축 비활성화
        return data
    
    async def send_message(self, writer: asyncio.StreamWriter, message: Dict) -> None:
        """메시지를 전송합니다."""
        data = json.dumps(message).encode('utf-8')
        length = len(data)
        # 메시지 길이를 먼저 전송
        writer.write(struct.pack('!I', length))
        writer.write(data)
        await writer.drain()
    
    async def receive_message(self, reader: asyncio.StreamReader) -> Optional[Dict]:
        """메시지를 수신합니다."""
        try:
            # 메시지 길이 수신
            length_data = await reader.readexactly(4)
            length = struct.unpack('!I', length_data)[0]
            
            # 메시지 데이터 수신
            data = await reader.readexactly(length)
            return json.loads(data.decode('utf-8'))
        except (asyncio.IncompleteReadError, json.JSONDecodeError) as e:
            self.logger.error(f"메시지 수신 오류: {e}")
            return None


class FileTransferServer:
    """파일 전송 서버"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8833):
        self.host = host
        self.port = port
        self.protocol = FileTransferProtocol()
        self.server = None
        self.logger = logging.getLogger(__name__)
        self.performance_monitor = PerformanceMonitor(self.logger)
        self.upload_state = None
        
        # 시스템 정보 로그
        cpu_count = psutil.cpu_count(logical=True)
        memory = psutil.virtual_memory()
        self.logger.info(f"서버 시스템 정보: CPU {cpu_count}코어, 메모리 {memory.total/(1024**3):.1f}GB")
    
    async def start(self):
        """서버를 시작합니다."""
        try:
            self.server = await asyncio.start_server(
                self.handle_client, self.host, self.port
            )
            self.logger.info(f"파일 전송 서버가 {self.host}:{self.port}에서 시작되었습니다.")
            
            # 성능 모니터링 시작
            self.performance_monitor.start_monitoring()
            
            async with self.server:
                await self.server.serve_forever()
        except Exception as e:
            self.logger.error(f"서버 시작 실패: {e}")
            raise
    
    async def stop(self):
        """서버를 중지합니다."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.performance_monitor.stop_monitoring()
            self.logger.info("서버가 중지되었습니다.")
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """클라이언트 연결을 처리합니다."""
        client_addr = writer.get_extra_info('peername')
        self.logger.info(f"클라이언트 연결: {client_addr}")
        
        # TCP 소켓 최적화
        sock = writer.get_extra_info('socket')
        if sock:
            # TCP_NODELAY 설정 (Nagle 알고리즘 비활성화)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
            # 송수신 버퍼 크기 증가
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE * 4)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE * 4)
            
            self.logger.debug(f"클라이언트 {client_addr} TCP 소켓 최적화 완료")
        
        try:
            while True:
                try:
                    # 메시지 수신
                    message = await asyncio.wait_for(
                        self.protocol.receive_message(reader), 
                        timeout=TIMEOUT
                    )
                    
                    if not message:
                        self.logger.debug("클라이언트가 연결을 종료했습니다")
                        break
                    
                    command = message.get('command')
                    self.logger.debug(f"명령 수신: {command}")
                    
                    # 명령별 처리
                    if command == 'upload_start':
                        await self.handle_upload_start(reader, writer, message)
                    elif command == 'upload_chunk':
                        await self.handle_upload_chunk(reader, writer, message)
                    elif command == 'upload_finish':
                        await self.handle_upload_finish(reader, writer, message)
                    elif command == 'upload':
                        await self.handle_upload(reader, writer, message)
                    elif command == 'download':
                        await self.handle_download(reader, writer, message)
                    elif command == 'list':
                        await self.handle_list(reader, writer, message)
                    else:
                        self.logger.warning(f"알 수 없는 명령: {command}")
                        await self.protocol.send_message(writer, {
                            'status': 'error',
                            'message': f'알 수 없는 명령: {command}'
                        })
                
                except asyncio.TimeoutError:
                    self.logger.warning(f"클라이언트 타임아웃: {client_addr}")
                    break
                except ConnectionResetError:
                    self.logger.info(f"클라이언트가 연결을 재설정했습니다: {client_addr}")
                    break
                except Exception as e:
                    self.logger.error(f"클라이언트 처리 오류: {type(e).__name__}: {str(e)}")
                    break
                    
        except Exception as e:
            self.logger.error(f"클라이언트 연결 오류: {type(e).__name__}: {str(e)}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                self.logger.debug(f"연결 종료 오류: {e}")
            self.logger.info(f"클라이언트 연결 종료: {client_addr}")
    
    async def handle_upload_start(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, data: dict):
        """업로드 시작 처리 (고성능 버전)"""
        try:
            remote_path = data['path']
            file_size = data['size']
            expected_checksum = data['checksum']
            chunk_size = data.get('chunk_size', CHUNK_SIZE)
            
            self.logger.debug(f"업로드 시작 요청: {remote_path}, 크기: {file_size} bytes, 청크 크기: {chunk_size}")
            
            # 디렉토리 생성
            dir_path = os.path.dirname(remote_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
                self.logger.debug(f"디렉토리 생성: {dir_path}")
            
            # 임시 파일 경로
            temp_path = remote_path + '.tmp'
            
            # 서버 상태 초기화
            self.upload_state = {
                'remote_path': remote_path,
                'temp_path': temp_path,
                'file_size': file_size,
                'expected_checksum': expected_checksum,
                'chunk_size': chunk_size,
                'received_chunks': {},
                'total_chunks': (file_size + chunk_size - 1) // chunk_size,
                'temp_file': None,
                'decompress_queue': asyncio.Queue(maxsize=PIPELINE_SIZE),
                'write_queue': asyncio.Queue(maxsize=PIPELINE_SIZE),
                'max_workers': min(psutil.cpu_count(logical=True) * 2, MAX_CONCURRENT_CHUNKS * 2)
            }
            
            # 임시 파일 열기
            self.upload_state['temp_file'] = await aiofiles.open(temp_path, 'wb')
            
            # 백그라운드 처리 태스크 시작
            self.decompress_tasks = []
            for i in range(self.upload_state['max_workers']):
                task = asyncio.create_task(
                    self._decompress_chunks_async(
                        self.upload_state['decompress_queue'],
                        self.upload_state['write_queue']
                    )
                )
                self.decompress_tasks.append(task)
            
            self.write_task = asyncio.create_task(
                self._write_chunks_async(
                    self.upload_state['write_queue'],
                    self.upload_state['temp_file']
                )
            )
            
            self.logger.info(f"고성능 업로드 준비 완료: {self.upload_state['max_workers']} 워커")
            
            await self.protocol.send_message(writer, {
                'status': 'ready',
                'message': '업로드 준비 완료'
            })
            
        except Exception as e:
            self.logger.error(f"업로드 시작 오류: {e}")
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'업로드 시작 실패: {str(e)}'
            })
    
    async def handle_upload_chunk(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, data: dict):
        """청크 업로드 처리 (고성능 버전)"""
        try:
            if not hasattr(self, 'upload_state') or not self.upload_state:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': '업로드가 시작되지 않았습니다'
                })
                return
            
            chunk_id = data.get('chunk_id', 0)
            chunk_size = data['size']
            original_size = data['original_size']
            expected_checksum = data['checksum']
            
            # 청크 데이터 수신
            compressed_data = await reader.readexactly(chunk_size)
            if len(compressed_data) != chunk_size:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': f'청크 크기 불일치: 예상 {chunk_size}, 실제 {len(compressed_data)}'
                })
                return
            
            # 압축 해제 큐에 추가 (백그라운드 처리)
            await self.upload_state['decompress_queue'].put((
                chunk_id, compressed_data, expected_checksum, original_size
            ))
            
            await self.protocol.send_message(writer, {
                'status': 'chunk_ok',
                'message': f'청크 {chunk_id} 수신 완료'
            })
            
        except Exception as e:
            self.logger.error(f"청크 업로드 오류: {e}")
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'청크 업로드 실패: {str(e)}'
            })
    
    async def _decompress_chunks_async(self, decompress_queue: asyncio.Queue, write_queue: asyncio.Queue):
        """청크를 압축 해제해서 쓰기 큐에 넣습니다."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            while True:
                try:
                    item = await decompress_queue.get()
                    if item is None:  # 종료 신호
                        break
                    
                    chunk_id, compressed_data, expected_checksum, original_size = item
                    
                    # CPU 집약적인 압축 해제를 스레드풀에서 실행
                    decompressed_data = await asyncio.get_event_loop().run_in_executor(
                        executor, self.protocol.decompress_data, compressed_data
                    )
                    
                    # 체크섬 검증
                    actual_checksum = await asyncio.get_event_loop().run_in_executor(
                        executor, self.protocol.calculate_checksum, decompressed_data
                    )
                    
                    if actual_checksum != expected_checksum:
                        self.logger.error(f"청크 {chunk_id} 체크섬 불일치")
                        continue
                    
                    if len(decompressed_data) != original_size:
                        self.logger.error(f"청크 {chunk_id} 크기 불일치")
                        continue
                    
                    await write_queue.put((chunk_id, decompressed_data))
                    
                except Exception as e:
                    self.logger.error(f"압축 해제 오류: {e}")
                    break
    
    async def _write_chunks_async(self, write_queue: asyncio.Queue, temp_file):
        """압축 해제된 청크를 파일에 씁니다."""
        received_chunks = {}
        next_chunk_id = 0
        
        while True:
            try:
                item = await write_queue.get()
                if item is None:  # 종료 신호
                    break
                
                chunk_id, chunk_data = item
                received_chunks[chunk_id] = chunk_data
                
                # 순서대로 파일에 쓰기
                while next_chunk_id in received_chunks:
                    await temp_file.write(received_chunks[next_chunk_id])
                    await temp_file.flush()
                    del received_chunks[next_chunk_id]
                    next_chunk_id += 1
                
            except Exception as e:
                self.logger.error(f"파일 쓰기 오류: {e}")
                break
    
    async def handle_upload_finish(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, data: dict):
        """업로드 완료 처리 (고성능 버전)"""
        try:
            if not hasattr(self, 'upload_state') or not self.upload_state:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': '업로드가 시작되지 않았습니다'
                })
                return
            
            # 모든 백그라운드 태스크 완료 대기
            self.logger.info("백그라운드 처리 완료 대기 중...")
            
            # 압축 해제 큐에 종료 신호
            for _ in range(self.upload_state['max_workers']):
                await self.upload_state['decompress_queue'].put(None)
            
            await asyncio.gather(*self.decompress_tasks)
            
            # 쓰기 큐에 종료 신호
            await self.upload_state['write_queue'].put(None)
            await self.write_task
            
            # 임시 파일 닫기
            await self.upload_state['temp_file'].close()
            
            # 최종 파일 체크섬 검증
            self.logger.info("최종 체크섬 검증 중...")
            actual_checksum = await self._calculate_file_checksum_parallel(
                self.upload_state['temp_path'],
                self.upload_state['max_workers']
            )
            
            if actual_checksum == self.upload_state['expected_checksum']:
                # 임시 파일을 최종 파일로 이동
                os.rename(self.upload_state['temp_path'], self.upload_state['remote_path'])
                
                self.logger.info(f"파일 업로드 완료: {self.upload_state['remote_path']}")
                await self.protocol.send_message(writer, {
                    'status': 'success',
                    'message': '파일 업로드 완료'
                })
            else:
                # 체크섬 불일치 시 임시 파일 삭제
                if os.path.exists(self.upload_state['temp_path']):
                    os.remove(self.upload_state['temp_path'])
                
                self.logger.error(f"최종 체크섬 불일치: 예상 {self.upload_state['expected_checksum']}, 실제 {actual_checksum}")
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': '파일 체크섬 불일치'
                })
            
            # 상태 정리
            self.upload_state = None
            
        except Exception as e:
            self.logger.error(f"업로드 완료 오류: {e}")
            
            # 정리 작업
            if hasattr(self, 'upload_state') and self.upload_state:
                try:
                    if self.upload_state['temp_file']:
                        await self.upload_state['temp_file'].close()
                    if os.path.exists(self.upload_state['temp_path']):
                        os.remove(self.upload_state['temp_path'])
                except:
                    pass
                self.upload_state = None
            
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'업로드 완료 실패: {str(e)}'
            })
    
    async def _calculate_file_checksum_parallel(self, file_path: str, max_workers: int) -> str:
        """파일 체크섬을 병렬로 계산합니다 (서버용)."""
        file_size = os.path.getsize(file_path)
        chunk_size = max(CHUNK_SIZE, file_size // max_workers)
        
        def calculate_chunk_hash(chunk_data):
            return xxhash.xxh64(chunk_data).digest()
        
        hasher = xxhash.xxh64()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            async with aiofiles.open(file_path, 'rb') as f:
                tasks = []
                position = 0
                
                while position < file_size:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    
                    # CPU 집약적인 해시 계산을 스레드풀에서 실행
                    task = asyncio.get_event_loop().run_in_executor(
                        executor, calculate_chunk_hash, chunk
                    )
                    tasks.append((position, task))
                    position += len(chunk)
                
                # 순서대로 결과 수집
                results = []
                for pos, task in tasks:
                    hash_digest = await task
                    results.append((pos, hash_digest))
                
                # 순서대로 정렬하여 최종 해시 계산
                results.sort(key=lambda x: x[0])
                for _, hash_digest in results:
                    hasher.update(hash_digest)
        
        return hasher.hexdigest()
    
    async def handle_upload(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, message: Dict):
        """기존 방식의 파일 업로드를 처리합니다 (하위 호환성)."""
        try:
            target_path = message['path']
            file_size = message['size']
            expected_checksum = message['checksum']
            
            self.logger.debug(f"업로드 요청 수신: {target_path}, 크기: {file_size} bytes")
            
            # 파일 크기 제한 (100MB)
            MAX_FILE_SIZE = 100 * 1024 * 1024
            if file_size > MAX_FILE_SIZE:
                error_msg = f'파일이 너무 큽니다: {file_size} bytes > {MAX_FILE_SIZE} bytes. 청크 업로드를 사용하세요.'
                self.logger.error(error_msg)
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': error_msg
                })
                return
            
            # 디렉토리 생성
            target_dir = os.path.dirname(target_path)
            if target_dir:
                self.logger.debug(f"디렉토리 생성: {target_dir}")
                os.makedirs(target_dir, exist_ok=True)
            
            # 파일 수신
            self.logger.debug("파일 데이터 수신 시작")
            received_data = b''
            remaining = file_size
            
            while remaining > 0:
                chunk_size = min(CHUNK_SIZE, remaining)
                chunk = await reader.readexactly(chunk_size)
                received_data += chunk
                remaining -= len(chunk)
                if len(received_data) % (1024 * 1024) == 0:
                    self.logger.debug(f"수신된 데이터: {len(received_data)}/{file_size} bytes")
            
            self.logger.debug(f"파일 데이터 수신 완료: {len(received_data)} bytes")
            
            # 압축 해제
            self.logger.debug("압축 해제 시작")
            decompressed_data = self.protocol.decompress_data(received_data)
            self.logger.debug(f"압축 해제 완료: {len(decompressed_data)} bytes")
            
            # 체크섬 검증
            self.logger.debug("체크섬 검증 시작")
            actual_checksum = self.protocol.calculate_checksum(decompressed_data)
            if actual_checksum != expected_checksum:
                error_msg = f'체크섬 불일치: 예상 {expected_checksum}, 실제 {actual_checksum}'
                self.logger.error(error_msg)
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': error_msg
                })
                return
            
            self.logger.debug("체크섬 검증 통과")
            
            # 파일 저장
            self.logger.debug(f"파일 저장 시작: {target_path}")
            async with aiofiles.open(target_path, 'wb') as f:
                await f.write(decompressed_data)
            
            self.logger.info(f"파일 업로드 완료: {target_path} ({len(decompressed_data)} bytes)")
            
            await self.protocol.send_message(writer, {
                'status': 'success',
                'message': '파일 업로드 완료'
            })
            
        except Exception as e:
            error_msg = f'업로드 오류: {type(e).__name__}: {str(e)}'
            self.logger.error(error_msg)
            try:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': error_msg
                })
            except:
                pass
    
    async def handle_download(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, message: Dict):
        """다운로드 요청을 고성능으로 처리합니다."""
        try:
            remote_path = message['path']
            self.logger.debug(f"다운로드 요청: {remote_path}")
            
            # 파일 존재 확인
            if not os.path.exists(remote_path):
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': f'파일을 찾을 수 없습니다: {remote_path}'
                })
                return
            
            if not os.path.isfile(remote_path):
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': f'파일이 아닙니다: {remote_path}'
                })
                return
            
            # 파일 정보 수집
            file_size = os.path.getsize(remote_path)
            
            # CPU 코어 수에 따른 동적 조정
            cpu_count = psutil.cpu_count(logical=True)
            max_workers = min(cpu_count * 2, MAX_CONCURRENT_CHUNKS * 2)
            
            # 파일 체크섬 계산 (병렬로)
            file_checksum = await self._calculate_file_checksum_parallel(remote_path, max_workers)
            
            # 클라이언트에게 파일 정보 전송
            await self.protocol.send_message(writer, {
                'status': 'success',
                'size': file_size,
                'checksum': file_checksum
            })
            
            self.logger.info(f"고성능 다운로드 시작: {remote_path} ({file_size} bytes, {max_workers} 워커)")
            
            # 고성능 병렬 전송
            await self._send_file_parallel(remote_path, writer, file_size, max_workers)
            
            self.logger.info(f"다운로드 완료: {remote_path}")
            
        except Exception as e:
            self.logger.error(f"다운로드 처리 오류: {e}")
            try:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': f'다운로드 실패: {str(e)}'
                })
            except:
                pass
    
    async def _send_file_parallel(self, file_path: str, writer: asyncio.StreamWriter, file_size: int, max_workers: int):
        """파일을 병렬로 전송합니다."""
        try:
            # 읽기 및 압축 파이프라인
            read_queue = asyncio.Queue(maxsize=PIPELINE_SIZE)
            compressed_queue = asyncio.Queue(maxsize=PIPELINE_SIZE)
            
            # 파일 읽기 태스크
            read_task = asyncio.create_task(
                self._read_file_chunks_async(file_path, file_size, read_queue)
            )
            
            # 압축 태스크들
            compress_tasks = []
            for i in range(max_workers):
                task = asyncio.create_task(
                    self._compress_file_chunks_async(read_queue, compressed_queue)
                )
                compress_tasks.append(task)
            
            # 전송 태스크
            send_task = asyncio.create_task(
                self._send_compressed_chunks_async(compressed_queue, writer)
            )
            
            # 모든 태스크 완료 대기
            await read_task
            
            # 압축 큐에 종료 신호
            for _ in range(max_workers):
                await read_queue.put(None)
            
            await asyncio.gather(*compress_tasks)
            
            # 전송 큐에 종료 신호
            await compressed_queue.put(None)
            
            await send_task
            
        except Exception as e:
            self.logger.error(f"병렬 전송 오류: {e}")
            raise
    
    async def _read_file_chunks_async(self, file_path: str, file_size: int, read_queue: asyncio.Queue):
        """파일을 청크 단위로 읽어서 큐에 넣습니다."""
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                while True:
                    chunk = await f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    await read_queue.put(chunk)
                    
        except Exception as e:
            self.logger.error(f"파일 읽기 오류: {e}")
    
    async def _compress_file_chunks_async(self, read_queue: asyncio.Queue, compressed_queue: asyncio.Queue):
        """청크를 압축해서 압축 큐에 넣습니다."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            while True:
                try:
                    chunk_data = await read_queue.get()
                    if chunk_data is None:  # 종료 신호
                        break
                    
                    # CPU 집약적인 압축을 스레드풀에서 실행
                    compressed_data = await asyncio.get_event_loop().run_in_executor(
                        executor, self.protocol.compress_data, chunk_data
                    )
                    
                    await compressed_queue.put(compressed_data)
                    
                except Exception as e:
                    self.logger.error(f"압축 오류: {e}")
                    break
    
    async def _send_compressed_chunks_async(self, compressed_queue: asyncio.Queue, writer: asyncio.StreamWriter):
        """압축된 청크를 전송합니다."""
        try:
            sent_bytes = 0
            start_time = time.time()
            
            while True:
                compressed_data = await compressed_queue.get()
                if compressed_data is None:  # 종료 신호
                    break
                
                writer.write(compressed_data)
                await writer.drain()
                
                sent_bytes += len(compressed_data)
                
                # 성능 통계 (매 100MB마다)
                if sent_bytes % (100 * 1024 * 1024) == 0:
                    elapsed = time.time() - start_time
                    speed_mbps = (sent_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    
                    self.logger.info(f"전송 속도: {speed_mbps:.1f} MB/s ({sent_bytes} bytes 전송)")
                    
        except Exception as e:
            self.logger.error(f"청크 전송 오류: {e}")
            raise
    
    async def handle_list(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, message: Dict):
        """파일 목록을 처리합니다."""
        try:
            directory = message.get('path', '.')
            files = []
            
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                stat = os.stat(item_path)
                
                files.append({
                    'name': item,
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                    'is_directory': os.path.isdir(item_path)
                })
            
            await self.protocol.send_message(writer, {
                'status': 'success',
                'files': files
            })
            
        except Exception as e:
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'목록 조회 오류: {e}'
            })


class FileTransferClient:
    """파일 전송 클라이언트"""
    
    def __init__(self, host: str = 'localhost', port: int = 8833):
        self.host = host
        self.port = port
        self.protocol = FileTransferProtocol()
        self.reader = None
        self.writer = None
        self.logger = logging.getLogger(__name__)
        self.performance_monitor = PerformanceMonitor(self.logger)
        
        # 시스템 정보 로그
        cpu_count = psutil.cpu_count(logical=True)
        memory = psutil.virtual_memory()
        self.logger.info(f"시스템 정보: CPU {cpu_count}코어, 메모리 {memory.total/(1024**3):.1f}GB")
    
    async def connect(self) -> bool:
        """서버에 연결합니다."""
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            
            # TCP 소켓 최적화
            sock = self.writer.get_extra_info('socket')
            if sock:
                # TCP_NODELAY 설정 (Nagle 알고리즘 비활성화)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                
                # 송수신 버퍼 크기 증가
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE * 4)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE * 4)
                
                self.logger.debug("TCP 소켓 최적화 완료")
            
            self.logger.info(f"서버에 연결되었습니다: {self.host}:{self.port}")
            return True
        except Exception as e:
            self.logger.error(f"서버 연결 실패: {e}")
            return False
    
    async def disconnect(self):
        """서버 연결을 종료합니다."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
                self.logger.info("서버 연결이 종료되었습니다")
            except Exception as e:
                self.logger.debug(f"연결 종료 오류: {e}")
    
    async def upload_file(self, local_path: str, remote_path: str, retries: int = MAX_RETRIES) -> bool:
        """파일을 고성능으로 업로드합니다."""
        self.performance_monitor.start_monitoring()
        
        try:
            for attempt in range(retries + 1):
                try:
                    # 파일 크기 확인
                    file_size = os.path.getsize(local_path)
                    self.logger.debug(f"파일 크기: {file_size} bytes")
                    
                    # CPU 코어 수에 따른 동적 조정
                    cpu_count = psutil.cpu_count(logical=True)
                    max_workers = min(cpu_count * 2, MAX_CONCURRENT_CHUNKS * 2)
                    
                    self.logger.info(f"CPU 코어: {cpu_count}, 최대 워커: {max_workers}")
                    
                    # 전체 파일의 체크섬을 먼저 계산 (병렬로)
                    original_checksum = await self._calculate_file_checksum_parallel(local_path, max_workers)
                    self.logger.debug(f"원본 파일 체크섬: {original_checksum}")
                    
                    # 업로드 시작 요청 전송
                    await self.protocol.send_message(self.writer, {
                        'command': 'upload_start',
                        'path': remote_path,
                        'size': file_size,
                        'checksum': original_checksum,
                        'chunk_size': CHUNK_SIZE
                    })
                    
                    # 서버 응답 확인
                    response = await self.protocol.receive_message(self.reader)
                    if not response or response.get('status') != 'ready':
                        error_msg = response.get('message', '서버 준비 실패') if response else '응답 없음'
                        self.logger.error(f"업로드 시작 실패: {error_msg}")
                        continue
                    
                    self.logger.info("서버 준비 완료, 고성능 파일 전송 시작")
                    
                    # 고성능 병렬 전송
                    success = await self._upload_file_parallel(local_path, file_size, max_workers)
                    
                    if success:
                        # 업로드 완료 요청
                        await self.protocol.send_message(self.writer, {
                            'command': 'upload_finish'
                        })
                        
                        # 최종 응답 확인
                        response = await self.protocol.receive_message(self.reader)
                        if response and response.get('status') == 'success':
                            self.logger.info(f"파일 업로드 완료: {local_path} -> {remote_path}")
                            return True
                        else:
                            error_msg = response.get('message', '알 수 없는 오류') if response else '응답 없음'
                            self.logger.error(f"업로드 실패: {error_msg}")
                    else:
                        self.logger.error("병렬 전송 실패")
                        
                except FileNotFoundError as e:
                    self.logger.error(f"업로드 시도 {attempt + 1} 실패: 파일을 찾을 수 없음 - {local_path}")
                    return False
                except PermissionError as e:
                    self.logger.error(f"업로드 시도 {attempt + 1} 실패: 권한 없음 - {local_path}")
                    return False
                except ConnectionError as e:
                    self.logger.error(f"업로드 시도 {attempt + 1} 실패: 연결 오류 - {str(e)}")
                except asyncio.TimeoutError as e:
                    self.logger.error(f"업로드 시도 {attempt + 1} 실패: 타임아웃 - {str(e)}")
                except Exception as e:
                    self.logger.error(f"업로드 시도 {attempt + 1} 실패: {type(e).__name__}: {str(e)}")
                    
                if attempt < retries:
                    self.logger.info(f"1초 후 재시도합니다... ({attempt + 1}/{retries + 1})")
                    await asyncio.sleep(1)
                        
            return False
        finally:
            self.performance_monitor.stop_monitoring()
    
    async def _calculate_file_checksum_parallel(self, file_path: str, max_workers: int) -> str:
        """파일 체크섬을 병렬로 계산합니다."""
        file_size = os.path.getsize(file_path)
        chunk_size = max(CHUNK_SIZE, file_size // max_workers)
        
        def calculate_chunk_hash(chunk_data):
            return xxhash.xxh64(chunk_data).digest()
        
        hasher = xxhash.xxh64()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            async with aiofiles.open(file_path, 'rb') as f:
                tasks = []
                position = 0
                
                while position < file_size:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    
                    # CPU 집약적인 해시 계산을 스레드풀에서 실행
                    task = asyncio.get_event_loop().run_in_executor(
                        executor, calculate_chunk_hash, chunk
                    )
                    tasks.append((position, task))
                    position += len(chunk)
                
                # 순서대로 결과 수집
                results = []
                for pos, task in tasks:
                    hash_digest = await task
                    results.append((pos, hash_digest))
                
                # 순서대로 정렬하여 최종 해시 계산
                results.sort(key=lambda x: x[0])
                for _, hash_digest in results:
                    hasher.update(hash_digest)
        
        return hasher.hexdigest()
    
    async def _upload_file_parallel(self, file_path: str, file_size: int, max_workers: int) -> bool:
        """파일을 병렬로 업로드합니다."""
        try:
            # 청크 정보 계산
            total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            # 압축 및 전송 파이프라인
            chunk_queue = asyncio.Queue(maxsize=PIPELINE_SIZE)
            compressed_queue = asyncio.Queue(maxsize=PIPELINE_SIZE)
            
            # 파일 읽기 태스크
            read_task = asyncio.create_task(
                self._read_chunks_async(file_path, file_size, chunk_queue)
            )
            
            # 압축 태스크들
            compress_tasks = []
            for i in range(max_workers):
                task = asyncio.create_task(
                    self._compress_chunks_async(chunk_queue, compressed_queue)
                )
                compress_tasks.append(task)
            
            # 전송 태스크
            send_task = asyncio.create_task(
                self._send_chunks_async(compressed_queue, total_chunks)
            )
            
            # 모든 태스크 완료 대기
            await read_task
            
            # 압축 큐에 종료 신호
            for _ in range(max_workers):
                await chunk_queue.put(None)
            
            await asyncio.gather(*compress_tasks)
            
            # 전송 큐에 종료 신호
            await compressed_queue.put(None)
            
            result = await send_task
            return result
            
        except Exception as e:
            self.logger.error(f"병렬 업로드 오류: {e}")
            return False
    
    async def _read_chunks_async(self, file_path: str, file_size: int, chunk_queue: asyncio.Queue):
        """파일을 청크 단위로 읽어서 큐에 넣습니다."""
        try:
            chunk_id = 0
            async with aiofiles.open(file_path, 'rb') as f:
                while True:
                    chunk = await f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    await chunk_queue.put((chunk_id, chunk))
                    chunk_id += 1
                    
        except Exception as e:
            self.logger.error(f"파일 읽기 오류: {e}")
    
    async def _compress_chunks_async(self, chunk_queue: asyncio.Queue, compressed_queue: asyncio.Queue):
        """청크를 압축해서 압축 큐에 넣습니다."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            while True:
                try:
                    item = await chunk_queue.get()
                    if item is None:  # 종료 신호
                        break
                    
                    chunk_id, chunk_data = item
                    
                    # CPU 집약적인 압축을 스레드풀에서 실행
                    compressed_data = await asyncio.get_event_loop().run_in_executor(
                        executor, self.protocol.compress_data, chunk_data
                    )
                    
                    chunk_checksum = await asyncio.get_event_loop().run_in_executor(
                        executor, self.protocol.calculate_checksum, chunk_data
                    )
                    
                    await compressed_queue.put((chunk_id, compressed_data, chunk_checksum, len(chunk_data)))
                    
                except Exception as e:
                    self.logger.error(f"압축 오류: {e}")
                    break
    
    async def _send_chunks_async(self, compressed_queue: asyncio.Queue, total_chunks: int) -> bool:
        """압축된 청크를 전송합니다."""
        try:
            sent_chunks = 0
            start_time = time.time()
            total_bytes = 0
            
            while sent_chunks < total_chunks:
                item = await compressed_queue.get()
                if item is None:  # 종료 신호
                    break
                
                chunk_id, compressed_data, chunk_checksum, original_size = item
                
                # 청크 정보 전송
                await self.protocol.send_message(self.writer, {
                    'command': 'upload_chunk',
                    'chunk_id': chunk_id,
                    'size': len(compressed_data),
                    'original_size': original_size,
                    'checksum': chunk_checksum
                })
                
                # 청크 데이터 전송
                self.writer.write(compressed_data)
                await self.writer.drain()
                
                total_bytes += original_size
                sent_chunks += 1
                
                # 성능 통계 (매 100개 청크마다)
                if sent_chunks % 100 == 0 or sent_chunks == total_chunks:
                    elapsed = time.time() - start_time
                    speed_mbps = (total_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    progress = (sent_chunks / total_chunks) * 100
                    
                    self.logger.info(
                        f"전송 진행률: {progress:.1f}% ({sent_chunks}/{total_chunks} 청크) "
                        f"속도: {speed_mbps:.1f} MB/s"
                    )
                
                # 서버 응답 확인
                response = await self.protocol.receive_message(self.reader)
                if not response or response.get('status') != 'chunk_ok':
                    error_msg = response.get('message', '청크 전송 실패') if response else '응답 없음'
                    self.logger.error(f"청크 {chunk_id} 전송 실패: {error_msg}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"청크 전송 오류: {e}")
            return False
    
    async def download_file(self, remote_path: str, local_path: str, retries: int = MAX_RETRIES) -> bool:
        """파일을 고성능으로 다운로드합니다."""
        for attempt in range(retries + 1):
            try:
                # 다운로드 요청 전송
                await self.protocol.send_message(self.writer, {
                    'command': 'download',
                    'path': remote_path
                })
                
                # 서버 응답 확인
                response = await self.protocol.receive_message(self.reader)
                if not response:
                    self.logger.error("서버 응답 없음")
                    continue
                
                if response.get('status') == 'error':
                    error_msg = response.get('message', '알 수 없는 오류')
                    self.logger.error(f"다운로드 오류: {error_msg}")
                    if 'not found' in error_msg.lower():
                        return False  # 파일이 없으면 재시도하지 않음
                    continue
                
                # 파일 정보 확인
                file_size = response.get('size', 0)
                expected_checksum = response.get('checksum', '')
                
                if file_size == 0:
                    self.logger.error("파일 크기 정보 없음")
                    continue
                
                self.logger.info(f"다운로드 시작: {remote_path} ({file_size} bytes)")
                
                # CPU 코어 수에 따른 동적 조정
                cpu_count = psutil.cpu_count(logical=True)
                max_workers = min(cpu_count * 2, MAX_CONCURRENT_CHUNKS * 2)
                
                # 고성능 병렬 다운로드
                success = await self._download_file_parallel(local_path, file_size, expected_checksum, max_workers)
                
                if success:
                    self.logger.info(f"파일 다운로드 완료: {remote_path} -> {local_path}")
                    return True
                else:
                    self.logger.error("병렬 다운로드 실패")
                    
            except FileNotFoundError as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: 파일을 찾을 수 없음 - {remote_path}")
                return False
            except PermissionError as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: 권한 없음 - {local_path}")
                return False
            except ConnectionError as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: 연결 오류 - {str(e)}")
            except asyncio.TimeoutError as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: 타임아웃 - {str(e)}")
            except Exception as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: {type(e).__name__}: {str(e)}")
                
            if attempt < retries:
                self.logger.info(f"1초 후 재시도합니다... ({attempt + 1}/{retries + 1})")
                await asyncio.sleep(1)
                    
        return False
    
    async def _download_file_parallel(self, local_path: str, file_size: int, expected_checksum: str, max_workers: int) -> bool:
        """파일을 병렬로 다운로드합니다."""
        try:
            # 로컬 디렉토리 생성
            local_dir = os.path.dirname(local_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir, exist_ok=True)
            
            # 임시 파일 경로
            temp_path = local_path + '.tmp'
            
            # 압축 해제 및 쓰기 파이프라인
            compressed_queue = asyncio.Queue(maxsize=PIPELINE_SIZE)
            write_queue = asyncio.Queue(maxsize=PIPELINE_SIZE)
            
            # 압축 해제 태스크들
            decompress_tasks = []
            for i in range(max_workers):
                task = asyncio.create_task(
                    self._decompress_download_chunks_async(compressed_queue, write_queue)
                )
                decompress_tasks.append(task)
            
            # 파일 쓰기 태스크
            write_task = asyncio.create_task(
                self._write_download_chunks_async(write_queue, temp_path)
            )
            
            # 데이터 수신 태스크
            receive_task = asyncio.create_task(
                self._receive_download_data_async(file_size, compressed_queue)
            )
            
            # 모든 태스크 완료 대기
            success = await receive_task
            
            if success:
                # 압축 해제 큐에 종료 신호
                for _ in range(max_workers):
                    await compressed_queue.put(None)
                
                await asyncio.gather(*decompress_tasks)
                
                # 쓰기 큐에 종료 신호
                await write_queue.put(None)
                
                await write_task
                
                # 최종 체크섬 검증
                actual_checksum = await self._calculate_file_checksum_parallel(temp_path, max_workers)
                
                if actual_checksum == expected_checksum:
                    # 임시 파일을 최종 파일로 이동
                    os.rename(temp_path, local_path)
                    return True
                else:
                    self.logger.error(f"다운로드 체크섬 불일치: 예상 {expected_checksum}, 실제 {actual_checksum}")
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    return False
            else:
                # 실패 시 임시 파일 삭제
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return False
                
        except Exception as e:
            self.logger.error(f"병렬 다운로드 오류: {e}")
            return False
    
    async def _receive_download_data_async(self, file_size: int, compressed_queue: asyncio.Queue) -> bool:
        """다운로드 데이터를 수신합니다."""
        try:
            received_size = 0
            start_time = time.time()
            
            while received_size < file_size:
                # 청크 크기 정보 수신
                chunk_size = min(CHUNK_SIZE, file_size - received_size)
                compressed_data = await self.reader.readexactly(chunk_size)
                
                if not compressed_data:
                    self.logger.error("데이터 수신 중단")
                    return False
                
                await compressed_queue.put(compressed_data)
                received_size += len(compressed_data)
                
                # 성능 통계
                if received_size % (100 * 1024 * 1024) == 0 or received_size == file_size:
                    elapsed = time.time() - start_time
                    speed_mbps = (received_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    progress = (received_size / file_size) * 100
                    
                    self.logger.info(
                        f"다운로드 진행률: {progress:.1f}% ({received_size}/{file_size} bytes) "
                        f"속도: {speed_mbps:.1f} MB/s"
                    )
            
            return True
            
        except Exception as e:
            self.logger.error(f"데이터 수신 오류: {e}")
            return False
    
    async def _decompress_download_chunks_async(self, compressed_queue: asyncio.Queue, write_queue: asyncio.Queue):
        """다운로드된 청크를 압축 해제합니다."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            while True:
                try:
                    compressed_data = await compressed_queue.get()
                    if compressed_data is None:  # 종료 신호
                        break
                    
                    # CPU 집약적인 압축 해제를 스레드풀에서 실행
                    decompressed_data = await asyncio.get_event_loop().run_in_executor(
                        executor, self.protocol.decompress_data, compressed_data
                    )
                    
                    await write_queue.put(decompressed_data)
                    
                except Exception as e:
                    self.logger.error(f"압축 해제 오류: {e}")
                    break
    
    async def _write_download_chunks_async(self, write_queue: asyncio.Queue, temp_path: str):
        """압축 해제된 청크를 파일에 씁니다."""
        try:
            async with aiofiles.open(temp_path, 'wb') as f:
                while True:
                    chunk_data = await write_queue.get()
                    if chunk_data is None:  # 종료 신호
                        break
                    
                    await f.write(chunk_data)
                    await f.flush()
                    
        except Exception as e:
            self.logger.error(f"파일 쓰기 오류: {e}")
    
    async def transfer_directory(self, local_dir: str, remote_dir: str, upload: bool = True) -> bool:
        """디렉토리를 재귀적으로 전송합니다."""
        success_count = 0
        total_count = 0
        
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_file = os.path.join(root, file)
                relative_path = os.path.relpath(local_file, local_dir)
                remote_file = os.path.join(remote_dir, relative_path).replace('\\', '/')
                
                total_count += 1
                
                if upload:
                    success = await self.upload_file(local_file, remote_file)
                else:
                    success = await self.download_file(remote_file, local_file)
                
                if success:
                    success_count += 1
        
        self.logger.info(f"디렉토리 전송 완료: {success_count}/{total_count} 파일")
        return success_count == total_count


def setup_logging(level: str = 'INFO'):
    """로깅을 설정합니다."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('file_transfer.log')
        ]
    )


async def run_server(host: str, port: int):
    """서버를 실행합니다."""
    server = FileTransferServer(host, port)
    
    def signal_handler(signum, frame):
        asyncio.create_task(server.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()


async def run_client(host: str, port: int, command: str, local_path: str, remote_path: str):
    """클라이언트를 실행합니다."""
    client = FileTransferClient(host, port)
    
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


def optimize_system_resources():
    """시스템 리소스를 최적화합니다."""
    try:
        import resource
        
        # 파일 디스크립터 제한 증가
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_limit = min(hard, 65536)
        resource.setrlimit(resource.RLIMIT_NOFILE, (new_limit, hard))
        
        # 메모리 제한 확인
        memory_limit = resource.getrlimit(resource.RLIMIT_AS)
        
        print(f"시스템 최적화 완료:")
        print(f"  - 파일 디스크립터 제한: {soft} -> {new_limit}")
        print(f"  - 메모리 제한: {memory_limit[0] if memory_limit[0] != -1 else '무제한'}")
        print(f"  - CPU 코어 수: {psutil.cpu_count(logical=True)}")
        print(f"  - 총 메모리: {psutil.virtual_memory().total/(1024**3):.1f}GB")
        
    except ImportError:
        print("리소스 최적화를 위해서는 Unix 시스템이 필요합니다.")
    except Exception as e:
        print(f"시스템 최적화 실패: {e}")

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='고성능 파일 전송 프로그램')
    parser.add_argument('--mode', choices=['server', 'client'], required=True,
                        help='실행 모드')
    parser.add_argument('--host', default='localhost',
                        help='서버 호스트 (기본값: localhost)')
    parser.add_argument('--port', type=int, default=8833,
                        help='서버 포트 (기본값: 8833)')
    parser.add_argument('--command', choices=['upload', 'download'],
                        help='클라이언트 명령')
    parser.add_argument('--local', help='로컬 파일/디렉토리 경로')
    parser.add_argument('--remote', help='원격 파일/디렉토리 경로')
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='로그 레벨')
    parser.add_argument('--optimize', action='store_true', 
                        help='시스템 리소스 최적화 활성화')
    
    args = parser.parse_args()
    
    # 시스템 리소스 최적화
    if args.optimize or args.mode == 'server':
        optimize_system_resources()
    
    setup_logging(args.log_level)
    
    if args.mode == 'server':
        print(f"파일 전송 서버를 시작합니다: {args.host}:{args.port}")
        asyncio.run(run_server(args.host, args.port))
    elif args.mode == 'client':
        if not all([args.command, args.local, args.remote]):
            print("클라이언트 모드에서는 --command, --local, --remote 옵션이 필요합니다.")
            return
        
        print(f"파일 전송을 시작합니다: {args.command}")
        success = asyncio.run(run_client(args.host, args.port, args.command, args.local, args.remote))
        if success:
            print("전송이 완료되었습니다.")
        else:
            print("전송 중 오류가 발생했습니다.")


if __name__ == '__main__':
    main() 