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


# 상수 정의
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
COMPRESSION_LEVEL = 3  # zstd 압축 레벨
MAX_RETRIES = 3
TIMEOUT = 30
BUFFER_SIZE = 64 * 1024  # 64KB 버퍼


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
        """데이터를 압축합니다."""
        return self.compressor.compress(data)
    
    def decompress_data(self, data: bytes) -> bytes:
        """데이터를 압축해제합니다."""
        return self.decompressor.decompress(data)
    
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
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8888):
        self.host = host
        self.port = port
        self.protocol = FileTransferProtocol()
        self.logger = logging.getLogger(__name__)
        self.server = None
        self.running = False
        
    async def start(self):
        """서버를 시작합니다."""
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        self.running = True
        
        addr = self.server.sockets[0].getsockname()
        self.logger.info(f"파일 전송 서버가 {addr}에서 시작되었습니다.")
        
        async with self.server:
            await self.server.serve_forever()
    
    async def stop(self):
        """서버를 중지합니다."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.running = False
            self.logger.info("서버가 중지되었습니다.")
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """클라이언트 연결을 처리합니다."""
        client_addr = writer.get_extra_info('peername')
        self.logger.info(f"클라이언트 연결: {client_addr}")
        
        try:
            while True:
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
            expected_checksum = message['checksum']
            
            self.logger.debug(f"업로드 요청 수신: {target_path}, 크기: {file_size} bytes")
            
            # 디렉토리 생성
            target_dir = os.path.dirname(target_path)
            if target_dir:  # 디렉토리가 있는 경우에만 생성
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
                if len(received_data) % (1024 * 1024) == 0:  # 1MB마다 로그
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
            
        except asyncio.IncompleteReadError as e:
            error_msg = f'데이터 읽기 오류: {str(e)}'
            self.logger.error(error_msg)
            try:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': error_msg
                })
            except:
                pass
        except PermissionError as e:
            error_msg = f'권한 오류: {str(e)}'
            self.logger.error(error_msg)
            try:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': error_msg
                })
            except:
                pass
        except OSError as e:
            error_msg = f'파일 시스템 오류: {str(e)}'
            self.logger.error(error_msg)
            try:
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': error_msg
                })
            except:
                pass
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
        """파일 다운로드를 처리합니다."""
        try:
            file_path = message['path']
            
            if not os.path.exists(file_path):
                await self.protocol.send_message(writer, {
                    'status': 'error',
                    'message': '파일을 찾을 수 없습니다'
                })
                return
            
            # 파일 읽기
            async with aiofiles.open(file_path, 'rb') as f:
                file_data = await f.read()
            
            # 체크섬 계산
            checksum = self.protocol.calculate_checksum(file_data)
            
            # 압축
            compressed_data = self.protocol.compress_data(file_data)
            
            # 파일 정보 전송
            await self.protocol.send_message(writer, {
                'status': 'success',
                'size': len(compressed_data),
                'checksum': checksum,
                'original_size': len(file_data)
            })
            
            # 파일 데이터 전송
            writer.write(compressed_data)
            await writer.drain()
            
        except Exception as e:
            await self.protocol.send_message(writer, {
                'status': 'error',
                'message': f'다운로드 오류: {e}'
            })
    
    async def handle_list(self, writer: asyncio.StreamWriter, message: Dict):
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
    
    def __init__(self, host: str, port: int = 8888):
        self.host = host
        self.port = port
        self.protocol = FileTransferProtocol()
        self.logger = logging.getLogger(__name__)
        self.reader = None
        self.writer = None
        self.progress = TransferProgress()
        
    async def connect(self) -> bool:
        """서버에 연결합니다."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=TIMEOUT
            )
            self.logger.info(f"서버에 연결되었습니다: {self.host}:{self.port}")
            return True
        except Exception as e:
            self.logger.error(f"서버 연결 실패: {e}")
            return False
    
    async def disconnect(self):
        """서버 연결을 끊습니다."""
        if self.writer:
            await self.protocol.send_message(self.writer, {'command': 'close'})
            self.writer.close()
            await self.writer.wait_closed()
            self.logger.info("서버 연결을 종료했습니다.")
    
    async def upload_file(self, local_path: str, remote_path: str, retries: int = MAX_RETRIES) -> bool:
        """파일을 업로드합니다."""
        for attempt in range(retries + 1):
            try:
                # 파일 크기 확인
                file_size = os.path.getsize(local_path)
                self.logger.debug(f"파일 크기: {file_size} bytes")
                
                # 파일을 청크 단위로 읽어서 압축하고 체크섬 계산
                hasher = xxhash.xxh64()
                compressor = zstd.ZstdCompressor(level=self.protocol.compression_level)
                compressed_chunks = []
                total_compressed_size = 0
                
                # 스트리밍 압축을 위한 compressor 객체 생성
                compress_obj = compressor.compressobj()
                
                async with aiofiles.open(local_path, 'rb') as f:
                    while True:
                        chunk = await f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        
                        hasher.update(chunk)
                        compressed_chunk = compress_obj.compress(chunk)
                        if compressed_chunk:
                            compressed_chunks.append(compressed_chunk)
                            total_compressed_size += len(compressed_chunk)
                
                # 마지막 압축 데이터
                final_chunk = compress_obj.flush()
                if final_chunk:
                    compressed_chunks.append(final_chunk)
                    total_compressed_size += len(final_chunk)
                
                checksum = hasher.hexdigest()
                
                self.logger.debug(f"파일 크기: {file_size} bytes, 압축 후: {total_compressed_size} bytes")
                
                # 업로드 요청 전송
                await self.protocol.send_message(self.writer, {
                    'command': 'upload',
                    'path': remote_path,
                    'size': total_compressed_size,
                    'checksum': checksum
                })
                
                self.logger.debug("업로드 요청 메시지 전송 완료")
                
                # 압축된 데이터 전송
                for chunk in compressed_chunks:
                    self.writer.write(chunk)
                await self.writer.drain()
                
                self.logger.debug("파일 데이터 전송 완료")
                
                # 응답 수신
                response = await self.protocol.receive_message(self.reader)
                self.logger.debug(f"서버 응답: {response}")
                
                if response and response.get('status') == 'success':
                    self.logger.info(f"파일 업로드 완료: {local_path} -> {remote_path}")
                    return True
                else:
                    error_msg = response.get('message', '알 수 없는 오류') if response else '응답 없음'
                    self.logger.error(f"업로드 실패: {error_msg}")
                    
            except FileNotFoundError as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: 파일을 찾을 수 없음 - {local_path}")
                return False  # 파일이 없으면 재시도할 필요 없음
            except PermissionError as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: 권한 없음 - {local_path}")
                return False  # 권한 문제는 재시도해도 소용없음
            except MemoryError as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: 메모리 부족 - 파일이 너무 큽니다")
                return False  # 메모리 부족은 재시도해도 소용없음
            except ConnectionError as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: 연결 오류 - {str(e)}")
            except asyncio.TimeoutError as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: 타임아웃 - {str(e)}")
            except Exception as e:
                self.logger.error(f"업로드 시도 {attempt + 1} 실패: {type(e).__name__}: {str(e)}")
                
            if attempt < retries:
                self.logger.info(f"1초 후 재시도합니다... ({attempt + 1}/{retries + 1})")
                await asyncio.sleep(1)  # 재시도 전 대기
                    
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
                
                # 응답 수신
                response = await self.protocol.receive_message(self.reader)
                if not response or response.get('status') != 'success':
                    error_msg = response.get('message', '알 수 없는 오류') if response else '응답 없음'
                    self.logger.error(f"다운로드 실패: {error_msg}")
                    continue
                
                file_size = response['size']
                expected_checksum = response['checksum']
                
                # 파일 데이터 수신
                compressed_data = await self.reader.readexactly(file_size)
                
                # 압축 해제
                file_data = self.protocol.decompress_data(compressed_data)
                
                # 체크섬 검증
                actual_checksum = self.protocol.calculate_checksum(file_data)
                if actual_checksum != expected_checksum:
                    self.logger.error("체크섬 불일치")
                    continue
                
                # 디렉토리 생성
                local_dir = os.path.dirname(local_path)
                if local_dir:  # 디렉토리가 있는 경우에만 생성
                    os.makedirs(local_dir, exist_ok=True)
                
                # 파일 저장
                async with aiofiles.open(local_path, 'wb') as f:
                    await f.write(file_data)
                
                self.logger.info(f"파일 다운로드 완료: {remote_path} -> {local_path}")
                return True
                
            except Exception as e:
                self.logger.error(f"다운로드 시도 {attempt + 1} 실패: {e}")
                if attempt < retries:
                    await asyncio.sleep(1)
                    
        return False
    
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


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='고성능 파일 전송 프로그램')
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
    
    args = parser.parse_args()
    
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