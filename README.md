# 고성능 파일 전송 프로그램

리눅스 서버 간 고속 파일 전송을 위한 Python 프로그램입니다. CPU와 네트워크 대역폭을 최대한 활용하면서 데이터 무결성을 보장합니다.

## ✨ 주요 기능

- **고성능 전송**: 비동기 I/O와 멀티스레딩으로 CPU/네트워크 최대 활용
- **데이터 압축**: zstandard 압축으로 네트워크 대역폭 효율성 증대
- **무결성 보장**: xxHash를 이용한 체크섬 검증
- **실패 복구**: 자동 재시도 및 오류 복구 메커니즘
- **진행률 표시**: 실시간 진행률 및 성능 모니터링
- **대용량 지원**: 파일 크기 제한 없이 청크 단위 전송

## 📋 요구사항

- Python 3.7+
- Linux 운영체제
- 필수 패키지: `pip install -r requirements.txt`

## 🚀 설치 및 설정

1. **패키지 설치**:
   ```bash
   pip install -r requirements.txt
   ```

2. **실행 권한 부여**:
   ```bash
   chmod +x file_transfer.py
   ```

## 📖 사용법

### 서버 시작

```bash
# 기본 포트(8888)로 서버 시작
python file_transfer.py --mode server

# 특정 호스트/포트로 서버 시작
python file_transfer.py --mode server --host 0.0.0.0 --port 9999
```

### 파일 업로드

```bash
# 단일 파일 업로드
python file_transfer.py --mode client --host 서버IP --command upload --local 로컬파일 --remote 원격파일

# 디렉토리 업로드
python file_transfer.py --mode client --host 서버IP --command upload --local 로컬디렉토리 --remote 원격디렉토리
```

### 파일 다운로드

```bash
# 단일 파일 다운로드
python file_transfer.py --mode client --host 서버IP --command download --remote 원격파일 --local 로컬파일

# 디렉토리 다운로드
python file_transfer.py --mode client --host 서버IP --command download --remote 원격디렉토리 --local 로컬디렉토리
```

## 🔧 고급 옵션

### 압축 레벨 조정
```bash
# 높은 압축률 (느림)
python file_transfer.py --mode server --compression-level 22

# 낮은 압축률 (빠름)
python file_transfer.py --mode server --compression-level 1
```

### 로그 레벨 설정
```bash
python file_transfer.py --mode server --log-level DEBUG
```

## 📊 성능 특성

| 항목 | 값 |
|------|-----|
| 기본 청크 크기 | 1MB |
| 최대 재시도 횟수 | 3회 |
| 연결 타임아웃 | 30초 |
| 압축 알고리즘 | zstandard |
| 체크섬 알고리즘 | xxHash64 |

## 🧪 테스트 실행

자동화된 테스트 스위트를 실행하여 모든 기능을 검증할 수 있습니다:

```bash
python test_transfer.py
```

테스트 항목:
- 파일 업로드/다운로드
- 디렉토리 전송
- 오류 복구
- 성능 측정
- 데이터 무결성 검증

## 📈 성능 최적화 팁

1. **네트워크 최적화**:
   - 기가비트 이더넷 이상 사용 권장
   - MTU 크기 최적화 (9000 바이트 점보 프레임)

2. **시스템 최적화**:
   - TCP 버퍼 크기 증가
   - 파일 시스템: ext4 또는 xfs 권장
   - SSD 사용 시 성능 향상

3. **프로그램 설정**:
   - SSD 환경에서는 압축 레벨을 낮춤 (속도 우선)
   - 네트워크가 병목인 경우 압축 레벨을 높임 (압축률 우선)

## 🔒 보안 고려사항

- 내부 네트워크에서만 사용 권장
- 방화벽에서 사용 포트 제한
- 필요시 VPN이나 SSH 터널 사용
- 정기적인 로그 모니터링

## 🐛 문제 해결

### 연결 오류
```bash
# 방화벽 설정 확인
sudo ufw status
sudo firewall-cmd --list-ports

# 포트 사용 확인
netstat -tlnp | grep :8888
```

### 성능 문제
```bash
# 시스템 리소스 모니터링
htop
iotop
nethogs
```

### 로그 확인
```bash
tail -f file_transfer.log
```

## 📚 예제

### 1. 로그 파일 백업
```bash
# 서버 시작
python file_transfer.py --mode server --host 0.0.0.0 --port 8888

# 로그 디렉토리 백업
python file_transfer.py --mode client --host backup-server \
  --command upload --local /var/log --remote /backup/logs/$(date +%Y%m%d)
```

### 2. 데이터베이스 백업 전송
```bash
# 대용량 데이터베이스 백업 파일 전송
python file_transfer.py --mode client --host db-backup-server \
  --command upload --local /backup/db_backup.sql.gz --remote /storage/db_backup_$(date +%Y%m%d).sql.gz
```

### 3. 개발 환경 동기화
```bash
# 개발 코드 동기화
python file_transfer.py --mode client --host dev-server \
  --command upload --local ./project --remote /home/dev/project
```

## 🔄 업데이트 및 유지보수

### 의존성 업데이트
```bash
pip install --upgrade -r requirements.txt
```

### 성능 모니터링
- 로그 파일 정기 확인
- 전송 속도 추적
- 오류율 모니터링

## 📞 지원

문제가 발생하거나 개선 사항이 있으면 이슈를 등록해주세요.

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

**참고**: 이 프로그램은 고성능 파일 전송을 위해 설계되었으며, 안정적인 네트워크 환경에서 최적의 성능을 발휘합니다. 