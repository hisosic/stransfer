#!/usr/bin/env python3
"""
간단한 파일 전송 테스트
"""

import asyncio
import os
import tempfile
import sys
import logging

# 현재 디렉토리의 file_transfer 모듈 import
sys.path.insert(0, '.')
from file_transfer import FileTransferServer, FileTransferClient

# 로깅 설정
logging.basicConfig(level=logging.INFO)


async def test_basic_transfer():
    """기본 파일 전송 테스트"""
    print("🚀 기본 파일 전송 테스트 시작")
    
    # 테스트용 파일 생성
    test_content = "안녕하세요! 이것은 테스트 파일입니다.\n한글과 영어가 모두 포함되어 있습니다."
    test_file = "test_input.txt"
    output_file = "test_output.txt"
    
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_content)
    
    # 서버 시작
    server = FileTransferServer('localhost', 9000)
    server_task = asyncio.create_task(server.start())
    
    # 서버 시작 대기
    await asyncio.sleep(1)
    
    try:
        # 클라이언트 연결 및 업로드
        client = FileTransferClient('localhost', 9000)
        
        if await client.connect():
            print("✅ 서버 연결 성공")
            
            # 파일 업로드
            if await client.upload_file(test_file, output_file):
                print("✅ 파일 업로드 성공")
                
                # 업로드된 파일 확인
                if os.path.exists(output_file):
                    with open(output_file, 'r', encoding='utf-8') as f:
                        result_content = f.read()
                    
                    if result_content == test_content:
                        print("✅ 파일 내용 검증 성공")
                        print("🎉 모든 테스트 통과!")
                        return True
                    else:
                        print("❌ 파일 내용 불일치")
                else:
                    print("❌ 업로드된 파일이 존재하지 않음")
            else:
                print("❌ 파일 업로드 실패")
                
            await client.disconnect()
        else:
            print("❌ 서버 연결 실패")
            
    except Exception as e:
        print(f"❌ 테스트 중 오류: {e}")
        
    finally:
        # 서버 종료
        await server.stop()
        server_task.cancel()
        
        # 테스트 파일 정리
        for file in [test_file, output_file]:
            if os.path.exists(file):
                os.remove(file)
    
    return False


async def test_compression_and_checksum():
    """압축 및 체크섬 테스트"""
    print("\n🔧 압축 및 체크섬 테스트")
    
    from file_transfer import FileTransferProtocol
    
    protocol = FileTransferProtocol()
    
    # 테스트 데이터
    test_data = b"Hello World! " * 1000  # 반복되는 데이터로 압축 효과 확인
    
    # 압축 테스트
    compressed = protocol.compress_data(test_data)
    decompressed = protocol.decompress_data(compressed)
    
    if decompressed == test_data:
        compression_ratio = len(compressed) / len(test_data) * 100
        print(f"✅ 압축/해제 성공 (압축률: {compression_ratio:.1f}%)")
    else:
        print("❌ 압축/해제 실패")
        return False
    
    # 체크섬 테스트
    checksum1 = protocol.calculate_checksum(test_data)
    checksum2 = protocol.calculate_checksum(test_data)
    
    if checksum1 == checksum2:
        print(f"✅ 체크섬 일관성 확인: {checksum1}")
    else:
        print("❌ 체크섬 불일치")
        return False
    
    # 다른 데이터의 체크섬
    other_data = test_data + b"extra"
    checksum3 = protocol.calculate_checksum(other_data)
    
    if checksum1 != checksum3:
        print("✅ 다른 데이터의 체크섬 다름 확인")
    else:
        print("❌ 다른 데이터의 체크섬이 같음")
        return False
    
    return True


async def test_performance():
    """간단한 성능 테스트"""
    print("\n⚡ 성능 테스트")
    
    import time
    import random
    
    # 1MB 랜덤 데이터 생성
    test_data = bytes(random.getrandbits(8) for _ in range(1024 * 1024))
    test_file = "perf_test.bin"
    
    with open(test_file, 'wb') as f:
        f.write(test_data)
    
    try:
        from file_transfer import FileTransferProtocol
        protocol = FileTransferProtocol()
        
        # 압축 성능 측정
        start_time = time.time()
        compressed = protocol.compress_data(test_data)
        compress_time = time.time() - start_time
        
        # 해제 성능 측정
        start_time = time.time()
        decompressed = protocol.decompress_data(compressed)
        decompress_time = time.time() - start_time
        
        # 체크섬 성능 측정
        start_time = time.time()
        checksum = protocol.calculate_checksum(test_data)
        checksum_time = time.time() - start_time
        
        original_size = len(test_data)
        compressed_size = len(compressed)
        compression_ratio = compressed_size / original_size * 100
        
        print(f"  원본 크기: {original_size:,} bytes")
        print(f"  압축 크기: {compressed_size:,} bytes ({compression_ratio:.1f}%)")
        print(f"  압축 시간: {compress_time:.3f}초 ({original_size/compress_time/1024/1024:.1f} MB/s)")
        print(f"  해제 시간: {decompress_time:.3f}초 ({original_size/decompress_time/1024/1024:.1f} MB/s)")
        print(f"  체크섬 시간: {checksum_time:.3f}초 ({original_size/checksum_time/1024/1024:.1f} MB/s)")
        print(f"  체크섬: {checksum}")
        
        if decompressed == test_data:
            print("✅ 성능 테스트 통과")
            return True
        else:
            print("❌ 데이터 무결성 실패")
            return False
            
    except Exception as e:
        print(f"❌ 성능 테스트 오류: {e}")
        return False
        
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)


async def main():
    """메인 테스트 함수"""
    print("=" * 50)
    print("고성능 파일 전송 프로그램 간단 테스트")
    print("=" * 50)
    
    tests = [
        ("압축 및 체크섬", test_compression_and_checksum()),
        ("성능 측정", test_performance()),
        ("기본 파일 전송", test_basic_transfer()),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_coro in tests:
        print(f"\n📋 {test_name} 테스트...")
        try:
            if await test_coro:
                passed += 1
                print(f"✅ {test_name} 성공")
            else:
                print(f"❌ {test_name} 실패")
        except Exception as e:
            print(f"❌ {test_name} 예외: {e}")
    
    print("\n" + "=" * 50)
    print(f"테스트 결과: {passed}/{total} 통과 ({passed/total*100:.1f}%)")
    if passed == total:
        print("🎉 모든 테스트가 성공했습니다!")
    else:
        print("⚠️  일부 테스트가 실패했습니다.")
    print("=" * 50)


if __name__ == '__main__':
    asyncio.run(main()) 