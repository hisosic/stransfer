# 🚀 고성능 파일 전송 시스템

리눅스 서버 간 고성능 파일 전송을 위한 Python 프로그램입니다. CPU와 네트워크 대역폭을 100% 활용하여 최대 성능으로 빠르고 안정적인 파일 전송을 제공합니다.

## ✨ 주요 기능

### 🔥 극한 성능 최적화
- **멀티스레드 병렬 처리**: CPU 코어 수 × 2 워커로 동시 처리
- **파이프라인 아키텍처**: 읽기/압축/전송 단계 완전 병렬화
- **대용량 청크**: 8MB 청크로 네트워크 효율성 극대화
- **TCP 소켓 최적화**: Nagle 알고리즘 비활성화, 4MB 버퍼
- **시스템 리소스 최적화**: 파일 디스크립터 자동 조정 (65536개)

### 🛡️ 안정성 및 무결성
- **zstandard 고속 압축**: 네트워크 대역폭 절약 (레벨 1 = 최고 속도)
- **xxHash64 체크섬**: 병렬 체크섬으로 빠른 무결성 검증
- **스마트 재시도**: 네트워크 오류 시 최대 3회 자동 재시도
- **청크별 검증**: 각 청크 개별 체크섬으로 오류 즉시 감지
- **안전한 전송**: 임시 파일 사용으로 원본 보호

### 📊 실시간 모니터링
- **성능 모니터링**: CPU, 메모리, 네트워크, 디스크 실시간 추적
- **상세 진행률**: 전송 속도, 압축률, 남은 시간 표시
- **성능 통계**: 전송 완료 후 상세한 성능 분석 리포트

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

## 성능 최적화

### 16G 네트워크 극한 최적화
- **청크 크기**: 128MB (극한 처리량)
- **TCP 버퍼**: 512MB 송수신 버퍼
- **워커 수**: CPU 코어 × 16 (극한 병렬 처리)
- **파이프라인**: 64단계 파이프라인
- **동시 청크**: 32개 동시 처리
- **네트워크 버퍼**: 1GB 시스템 버퍼 (Linux)

### 성능 벤치마크 (16G 네트워크 최적화)
- **10MB**: 업로드 283MB/s, 다운로드 353MB/s
- **50MB**: 업로드 375MB/s, 다운로드 436MB/s
- **100MB**: 업로드 440MB/s, 다운로드 527MB/s
- **500MB**: 업로드 590MB/s, 다운로드 593MB/s
- **평균**: 업로드 422MB/s, 다운로드 477MB/s

### 시스템 요구사항 (극한 성능)
- CPU: 16코어 이상 권장
- 메모리: 16GB 이상 권장
- 네트워크: 10G 이상 (16G 권장)
- 디스크: NVMe SSD 권장

## 극한 성능을 위한 사용법

### 1. 시스템 최적화 (Linux 서버)
```bash
# sudo 권한으로 실행하여 시스템 버퍼 최적화
sudo python file_transfer.py --optimize-system

# 또는 수동 설정
echo 1073741824 | sudo tee /proc/sys/net/core/rmem_max
echo 1073741824 | sudo tee /proc/sys/net/core/wmem_max
echo 100000 | sudo tee /proc/sys/net/core/netdev_max_backlog
echo "4096 65536 1073741824" | sudo tee /proc/sys/net/ipv4/tcp_rmem
echo "4096 65536 1073741824" | sudo tee /proc/sys/net/ipv4/tcp_wmem
```

### 2. 16G 네트워크 환경에서 30GB 파일 전송
```bash
# 서버 측 (16G 네트워크 최적화)
python file_transfer.py server --host 0.0.0.0 --port 8834

# 클라이언트 측 (극한 성능 업로드)
python file_transfer.py upload_large /path/to/30gb_file.tar /remote/path/30gb_file.tar --host server_ip --port 8834
```

### 3. 성능 모니터링
프로그램 실행 중 다음 정보가 실시간으로 표시됩니다:
- CPU 사용률 (목표: 80-100%)
- 메모리 사용률
- 네트워크 송수신 속도
- 디스크 I/O 속도
- 전송 진행률 (10MB마다 업데이트) 