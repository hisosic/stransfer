# 디렉토리 전송 기능 사용법

## 개요

`file_transfer.py`에 디렉토리를 지정하면 디렉토리 하위의 모든 파일과 서브디렉토리를 재귀적으로 전송하는 기능이 추가되었습니다.

## 주요 특징

- **재귀적 전송**: 디렉토리 하위의 모든 파일과 서브디렉토리를 자동으로 전송
- **디렉토리 구조 유지**: 원본 디렉토리 구조를 그대로 유지하여 전송
- **순차 처리**: 안정성을 위해 파일을 하나씩 순차적으로 전송
- **진행률 표시**: 실시간 전송 진행률과 통계 정보 제공
- **오류 처리**: 개별 파일 전송 실패 시에도 나머지 파일 계속 전송
- **압축 전송**: 각 파일을 압축하여 네트워크 효율성 향상
- **무결성 검증**: 체크섬을 통한 데이터 무결성 보장

## 명령어 사용법

### 1. 서버 실행
```bash
python file_transfer.py --mode server --host 0.0.0.0 --port 8834
```

### 2. 디렉토리 업로드
```bash
# 기본 디렉토리 업로드 (upload 명령어로 자동 감지)
python file_transfer.py --mode client --command upload --local /path/to/local/directory --remote /path/to/remote/directory --host SERVER_IP --port 8834

# 명시적 디렉토리 업로드
python file_transfer.py --mode client --command upload_dir --local /path/to/local/directory --remote /path/to/remote/directory --host SERVER_IP --port 8834
```

### 3. 디렉토리 다운로드 (향후 지원 예정)
```bash
python file_transfer.py --mode client --command download_dir --local /path/to/local/directory --remote /path/to/remote/directory --host SERVER_IP --port 8834
```

## 실제 사용 예시

### 예시 1: 간단한 디렉토리 전송
```bash
# 테스트 디렉토리 생성
mkdir -p my_project/src my_project/docs my_project/config
echo "main.py 내용" > my_project/src/main.py
echo "README 내용" > my_project/docs/README.md
echo "설정 파일" > my_project/config/app.conf

# 디렉토리 업로드
python file_transfer.py --mode client --command upload_dir --local my_project --remote backup/my_project --host localhost --port 8834
```

### 예시 2: 복잡한 디렉토리 구조 전송
```bash
# 복잡한 디렉토리 구조 생성
mkdir -p website/frontend/src/components website/frontend/public website/backend/api website/backend/models website/database/migrations
echo "App.js" > website/frontend/src/App.js
echo "Header.js" > website/frontend/src/components/Header.js
echo "index.html" > website/frontend/public/index.html
echo "users.py" > website/backend/api/users.py
echo "user_model.py" > website/backend/models/user.py
echo "001_create_users.sql" > website/database/migrations/001_create_users.sql

# 전체 웹사이트 디렉토리 업로드
python file_transfer.py --mode client --command upload_dir --local website --remote production/website --host 192.168.1.100 --port 8834
```

## 출력 예시

### 성공적인 디렉토리 전송
```
📁 파일 전송 시작: upload_dir
   로컬: complex_test
   원격: uploaded_complex_test
   서버: localhost:8834

2025-06-23 04:57:01,473 - FileTransferClient - INFO - 업로드 디렉토리 전송 시작: complex_test -> uploaded_complex_test
2025-06-23 04:57:01,476 - FileTransferClient - INFO - 업로드 대상: 7개 파일, 0.00GB
2025-06-23 04:57:01,480 - FileTransferClient - INFO - 순차 전송 모드: 7개 파일을 하나씩 처리

2025-06-23 04:57:01,480 - FileTransferClient - INFO - 📤 [1/7] branch.txt 업로드 시작...
2025-06-23 04:57:01,684 - FileTransferClient - INFO - ✅ branch.txt 업로드 완료 (14.3% - 1/7) 속도: 0.0MB/s
2025-06-23 04:57:01,684 - FileTransferClient - INFO - 📤 [2/7] sub1.txt 업로드 시작...
2025-06-23 04:57:01,889 - FileTransferClient - INFO - ✅ sub1.txt 업로드 완료 (28.6% - 2/7) 속도: 0.0MB/s
...

2025-06-23 04:57:02,909 - FileTransferClient - INFO - 디렉토리 전송 완료:
2025-06-23 04:57:02,909 - FileTransferClient - INFO -   - 총 파일: 7
2025-06-23 04:57:02,909 - FileTransferClient - INFO -   - 성공: 7 (100.0%)
2025-06-23 04:57:02,909 - FileTransferClient - INFO -   - 실패: 0
2025-06-23 04:57:02,909 - FileTransferClient - INFO -   - 총 크기: 0.00GB
2025-06-23 04:57:02,909 - FileTransferClient - INFO -   - 평균 속도: 0.0MB/s
2025-06-23 04:57:02,909 - FileTransferClient - INFO -   - 소요 시간: 1.4초

✅ 전송이 완료되었습니다.
```

## 기술적 세부사항

### 디렉토리 전송 과정
1. **파일 목록 수집**: `os.walk()`를 사용하여 모든 파일과 서브디렉토리 탐색
2. **디렉토리 구조 분석**: 상대 경로를 계산하여 원격 경로 매핑
3. **순차 파일 전송**: 안정성을 위해 파일을 하나씩 순차적으로 전송
4. **실시간 통계**: 진행률, 속도, 성공/실패 파일 수 추적

### 파일 처리 방식
- **압축**: zstandard 압축으로 네트워크 효율성 향상
- **체크섬**: xxHash64를 사용한 데이터 무결성 검증
- **자동 디렉토리 생성**: 서버 측에서 필요한 디렉토리 자동 생성
- **오류 복구**: 개별 파일 실패 시에도 나머지 파일 계속 처리

### 성능 특성
- **메모리 효율**: 각 파일을 개별적으로 처리하여 메모리 사용량 최소화
- **네트워크 최적화**: TCP_NODELAY 및 버퍼 크기 최적화
- **안정성 우선**: 동시성 문제를 피하기 위한 순차 처리

## 제한사항

1. **다운로드 디렉토리**: 현재 업로드만 지원, 다운로드는 향후 구현 예정
2. **순차 처리**: 안정성을 위해 병렬 처리 대신 순차 처리 사용
3. **파일 크기 제한**: 개별 파일은 메모리에 로드되므로 매우 큰 파일은 주의 필요

## 문제 해결

### 일반적인 문제
1. **연결 실패**: 서버가 실행 중인지, 포트가 열려있는지 확인
2. **권한 오류**: 대상 디렉토리에 쓰기 권한이 있는지 확인
3. **디스크 공간**: 대상 서버에 충분한 디스크 공간이 있는지 확인

### 디버깅
- 서버 로그 확인: `tail -f server.log`
- 클라이언트 상세 로그: 실행 시 자동으로 상세 로그 출력
- 네트워크 연결 테스트: `telnet SERVER_IP 8834`

## 향후 개선 계획

1. **디렉토리 다운로드**: 서버에서 클라이언트로 디렉토리 전송
2. **병렬 처리**: 안정성을 유지하면서 성능 향상
3. **중단/재개**: 대용량 디렉토리 전송 시 중단 후 재개 기능
4. **필터링**: 특정 파일 패턴 제외/포함 기능
5. **동기화**: rsync와 같은 증분 동기화 기능 