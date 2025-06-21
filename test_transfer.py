#!/usr/bin/env python3
"""
파일 전송 프로그램 테스트 스크립트
"""

import asyncio
import os
import shutil
import tempfile
import time
import random
import string
import logging
from pathlib import Path
import subprocess
import sys

# 테스트 설정
TEST_HOST = 'localhost'
TEST_PORT = 9999
TEST_DIR = 'test_data'
SERVER_DIR = 'server_files'


def setup_test_environment():
    """테스트 환경을 설정합니다."""
    # 테스트 디렉토리 정리
    for dir_name in [TEST_DIR, SERVER_DIR]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
        os.makedirs(dir_name, exist_ok=True)
    
    print("테스트 환경이 설정되었습니다.")


def generate_test_files():
    """테스트용 파일들을 생성합니다."""
    test_files = []
    
    # 작은 텍스트 파일
    small_file = os.path.join(TEST_DIR, 'small.txt')
    with open(small_file, 'w', encoding='utf-8') as f:
        f.write('안녕하세요! 이것은 작은 테스트 파일입니다.\n' * 10)
    test_files.append(small_file)
    
    # 중간 크기 바이너리 파일
    medium_file = os.path.join(TEST_DIR, 'medium.bin')
    with open(medium_file, 'wb') as f:
        data = bytearray(random.getrandbits(8) for _ in range(1024 * 1024))  # 1MB
        f.write(data)
    test_files.append(medium_file)
    
    # 큰 텍스트 파일
    large_file = os.path.join(TEST_DIR, 'large.txt')
    with open(large_file, 'w', encoding='utf-8') as f:
        for i in range(10000):
            line = ''.join(random.choices(string.ascii_letters + string.digits, k=100))
            f.write(f"Line {i:05d}: {line}\n")
    test_files.append(large_file)
    
    # 하위 디렉토리와 파일들
    sub_dir = os.path.join(TEST_DIR, 'subdir')
    os.makedirs(sub_dir, exist_ok=True)
    
    for i in range(5):
        sub_file = os.path.join(sub_dir, f'file_{i}.txt')
        with open(sub_file, 'w', encoding='utf-8') as f:
            f.write(f'하위 디렉토리 파일 {i}\n' * (i + 1) * 100)
        test_files.append(sub_file)
    
    print(f"테스트 파일 {len(test_files)}개가 생성되었습니다.")
    return test_files


def calculate_file_checksum(filepath):
    """파일의 체크섬을 계산합니다."""
    try:
        import xxhash
        with open(filepath, 'rb') as f:
            return xxhash.xxh64(f.read()).hexdigest()
    except ImportError:
        import hashlib
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()


async def start_test_server():
    """테스트 서버를 시작합니다."""
    print(f"테스트 서버를 시작합니다: {TEST_HOST}:{TEST_PORT}")
    
    # 서버 프로세스 시작
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'file_transfer.py',
        '--mode', 'server',
        '--host', TEST_HOST,
        '--port', str(TEST_PORT),
        '--log-level', 'WARNING',
        cwd=os.getcwd(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # 서버가 시작될 때까지 잠시 대기
    await asyncio.sleep(2)
    
    return proc


async def test_file_upload(test_files):
    """파일 업로드를 테스트합니다."""
    print("\n=== 파일 업로드 테스트 ===")
    
    success_count = 0
    total_count = len(test_files)
    
    for test_file in test_files:
        try:
            filename = os.path.basename(test_file)
            remote_path = os.path.join(SERVER_DIR, filename).replace('\\', '/')
            
            print(f"업로드 중: {filename}")
            
            # 업로드 명령 실행
            proc = await asyncio.create_subprocess_exec(
                sys.executable, 'file_transfer.py',
                '--mode', 'client',
                '--host', TEST_HOST,
                '--port', str(TEST_PORT),
                '--command', 'upload',
                '--local', test_file,
                '--remote', remote_path,
                '--log-level', 'ERROR',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                # 파일이 정상적으로 업로드되었는지 확인
                if os.path.exists(remote_path):
                    # 체크섬 비교
                    original_checksum = calculate_file_checksum(test_file)
                    uploaded_checksum = calculate_file_checksum(remote_path)
                    
                    if original_checksum == uploaded_checksum:
                        print(f"✓ {filename} 업로드 성공")
                        success_count += 1
                    else:
                        print(f"✗ {filename} 체크섬 불일치")
                else:
                    print(f"✗ {filename} 업로드 실패 - 파일이 생성되지 않음")
            else:
                print(f"✗ {filename} 업로드 실패 - 프로세스 오류")
                if stderr:
                    print(f"  오류: {stderr.decode()}")
                    
        except Exception as e:
            print(f"✗ {filename} 업로드 예외: {e}")
    
    success_rate = success_count / total_count * 100
    print(f"\n업로드 테스트 결과: {success_count}/{total_count} 성공 ({success_rate:.1f}%)")
    return success_count == total_count


async def test_file_download():
    """파일 다운로드를 테스트합니다."""
    print("\n=== 파일 다운로드 테스트 ===")
    
    download_dir = 'downloaded_files'
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir, exist_ok=True)
    
    # 서버 디렉토리의 파일 목록
    server_files = []
    for root, dirs, files in os.walk(SERVER_DIR):
        for file in files:
            server_files.append(os.path.join(root, file))
    
    success_count = 0
    total_count = len(server_files)
    
    for server_file in server_files:
        try:
            filename = os.path.basename(server_file)
            local_path = os.path.join(download_dir, filename)
            
            print(f"다운로드 중: {filename}")
            
            # 다운로드 명령 실행
            proc = await asyncio.create_subprocess_exec(
                sys.executable, 'file_transfer.py',
                '--mode', 'client',
                '--host', TEST_HOST,
                '--port', str(TEST_PORT),
                '--command', 'download',
                '--remote', server_file.replace('\\', '/'),
                '--local', local_path,
                '--log-level', 'ERROR',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                # 파일이 정상적으로 다운로드되었는지 확인
                if os.path.exists(local_path):
                    # 체크섬 비교
                    server_checksum = calculate_file_checksum(server_file)
                    downloaded_checksum = calculate_file_checksum(local_path)
                    
                    if server_checksum == downloaded_checksum:
                        print(f"✓ {filename} 다운로드 성공")
                        success_count += 1
                    else:
                        print(f"✗ {filename} 체크섬 불일치")
                else:
                    print(f"✗ {filename} 다운로드 실패 - 파일이 생성되지 않음")
            else:
                print(f"✗ {filename} 다운로드 실패 - 프로세스 오류")
                if stderr:
                    print(f"  오류: {stderr.decode()}")
                    
        except Exception as e:
            print(f"✗ {filename} 다운로드 예외: {e}")
    
    success_rate = success_count / total_count * 100
    print(f"\n다운로드 테스트 결과: {success_count}/{total_count} 성공 ({success_rate:.1f}%)")
    return success_count == total_count


async def test_directory_transfer():
    """디렉토리 전송을 테스트합니다."""
    print("\n=== 디렉토리 전송 테스트 ===")
    
    # 테스트 디렉토리 업로드
    remote_dir = "uploaded_directory"
    
    print(f"디렉토리 업로드 중: {TEST_DIR} -> {remote_dir}")
    
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'file_transfer.py',
        '--mode', 'client',
        '--host', TEST_HOST,
        '--port', str(TEST_PORT),
        '--command', 'upload',
        '--local', TEST_DIR,
        '--remote', remote_dir,
        '--log-level', 'ERROR',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await proc.communicate()
    
    if proc.returncode == 0:
        print("✓ 디렉토리 업로드 성공")
        
        # 업로드된 파일들 검증
        uploaded_files = []
        for root, dirs, files in os.walk(remote_dir):
            for file in files:
                uploaded_files.append(os.path.join(root, file))
        
        print(f"업로드된 파일 수: {len(uploaded_files)}")
        return True
    else:
        print("✗ 디렉토리 업로드 실패")
        if stderr:
            print(f"오류: {stderr.decode()}")
        return False


async def test_error_recovery():
    """오류 복구 기능을 테스트합니다."""
    print("\n=== 오류 복구 테스트 ===")
    
    # 존재하지 않는 파일 업로드 시도
    print("존재하지 않는 파일 업로드 테스트")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'file_transfer.py',
        '--mode', 'client',
        '--host', TEST_HOST,
        '--port', str(TEST_PORT),
        '--command', 'upload',
        '--local', 'nonexistent_file.txt',
        '--remote', 'test.txt',
        '--log-level', 'ERROR',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        print("✓ 존재하지 않는 파일 업로드 적절히 실패")
    else:
        print("✗ 존재하지 않는 파일 업로드가 성공함 (예상치 못함)")
    
    # 존재하지 않는 파일 다운로드 시도
    print("존재하지 않는 파일 다운로드 테스트")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'file_transfer.py',
        '--mode', 'client',
        '--host', TEST_HOST,
        '--port', str(TEST_PORT),
        '--command', 'download',
        '--remote', 'nonexistent_remote_file.txt',
        '--local', 'downloaded_test.txt',
        '--log-level', 'ERROR',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        print("✓ 존재하지 않는 파일 다운로드 적절히 실패")
        return True
    else:
        print("✗ 존재하지 않는 파일 다운로드가 성공함 (예상치 못함)")
        return False


async def performance_test():
    """성능 테스트를 수행합니다."""
    print("\n=== 성능 테스트 ===")
    
    # 큰 파일 생성 (10MB)
    large_file = os.path.join(TEST_DIR, 'performance_test.bin')
    file_size = 10 * 1024 * 1024  # 10MB
    
    print(f"{file_size // (1024*1024)}MB 파일 생성 중...")
    with open(large_file, 'wb') as f:
        data = bytearray(random.getrandbits(8) for _ in range(file_size))
        f.write(data)
    
    # 업로드 성능 측정
    remote_path = "performance_test.bin"
    
    print("성능 테스트 업로드 중...")
    start_time = time.time()
    
    proc = await asyncio.create_subprocess_exec(
        sys.executable, 'file_transfer.py',
        '--mode', 'client',
        '--host', TEST_HOST,
        '--port', str(TEST_PORT),
        '--command', 'upload',
        '--local', large_file,
        '--remote', remote_path,
        '--log-level', 'ERROR',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await proc.communicate()
    upload_time = time.time() - start_time
    
    if proc.returncode == 0:
        upload_speed = file_size / upload_time / (1024 * 1024)  # MB/s
        print(f"✓ 업로드 완료: {upload_time:.2f}초, {upload_speed:.2f} MB/s")
        
        # 다운로드 성능 측정
        download_path = os.path.join(TEST_DIR, 'downloaded_performance_test.bin')
        
        print("성능 테스트 다운로드 중...")
        start_time = time.time()
        
        proc = await asyncio.create_subprocess_exec(
            sys.executable, 'file_transfer.py',
            '--mode', 'client',
            '--host', TEST_HOST,
            '--port', str(TEST_PORT),
            '--command', 'download',
            '--remote', remote_path,
            '--local', download_path,
            '--log-level', 'ERROR',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await proc.communicate()
        download_time = time.time() - start_time
        
        if proc.returncode == 0:
            download_speed = file_size / download_time / (1024 * 1024)  # MB/s
            print(f"✓ 다운로드 완료: {download_time:.2f}초, {download_speed:.2f} MB/s")
            
            # 파일 무결성 검증
            original_checksum = calculate_file_checksum(large_file)
            downloaded_checksum = calculate_file_checksum(download_path)
            
            if original_checksum == downloaded_checksum:
                print("✓ 파일 무결성 검증 성공")
                return True
            else:
                print("✗ 파일 무결성 검증 실패")
                return False
        else:
            print("✗ 다운로드 실패")
            return False
    else:
        print("✗ 업로드 실패")
        return False


def cleanup_test_environment():
    """테스트 환경을 정리합니다."""
    dirs_to_clean = [TEST_DIR, SERVER_DIR, 'downloaded_files', 'uploaded_directory']
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
    
    # 로그 파일 정리
    log_files = ['file_transfer.log', 'enhanced_transfer.log']
    for log_file in log_files:
        if os.path.exists(log_file):
            os.remove(log_file)
    
    print("테스트 환경이 정리되었습니다.")


async def run_all_tests():
    """모든 테스트를 실행합니다."""
    print("고성능 파일 전송 프로그램 테스트 시작\n")
    
    # 테스트 환경 설정
    setup_test_environment()
    test_files = generate_test_files()
    
    # 서버 시작
    server_proc = await start_test_server()
    
    try:
        # 테스트 실행
        tests = [
            ("파일 업로드", test_file_upload(test_files)),
            ("파일 다운로드", test_file_download()),
            ("디렉토리 전송", test_directory_transfer()),
            ("오류 복구", test_error_recovery()),
            ("성능 테스트", performance_test())
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test_name, test_coro in tests:
            print(f"\n{'='*50}")
            print(f"테스트: {test_name}")
            print('='*50)
            
            try:
                result = await test_coro
                if result:
                    print(f"✓ {test_name} 통과")
                    passed_tests += 1
                else:
                    print(f"✗ {test_name} 실패")
            except Exception as e:
                print(f"✗ {test_name} 예외: {e}")
        
        # 최종 결과
        print(f"\n{'='*50}")
        print("테스트 결과 요약")
        print('='*50)
        print(f"통과: {passed_tests}/{total_tests}")
        success_rate = passed_tests / total_tests * 100
        print(f"성공률: {success_rate:.1f}%")
        
        if passed_tests == total_tests:
            print("🎉 모든 테스트가 성공했습니다!")
        else:
            print("⚠️ 일부 테스트가 실패했습니다.")
            
    finally:
        # 서버 종료
        if server_proc.returncode is None:
            server_proc.terminate()
            await server_proc.wait()
        
        # 환경 정리
        cleanup_test_environment()


if __name__ == '__main__':
    asyncio.run(run_all_tests()) 