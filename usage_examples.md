# 서버 간 파일 전송 사용 예시

## 시나리오: 서버 A ↔ 서버 B 간 파일 전송

### 1. 서버 A에서 파일 전송 서버 시작
```bash
# 서버 A (192.168.1.100)
python file_transfer.py --mode server --host 0.0.0.0 --port 8888
```

### 2. 서버 B → 서버 A로 파일 업로드

#### 단일 파일 업로드
```bash
# 서버 B에서 실행
python file_transfer.py --mode client --host 192.168.1.100 --port 8888 \
  --command upload \
  --local /home/user/data.txt \
  --remote /backup/data.txt
```

**결과**: 서버 B의 `/home/user/data.txt` → 서버 A의 `/backup/data.txt`

#### 디렉토리 업로드
```bash
# 서버 B에서 실행
python file_transfer.py --mode client --host 192.168.1.100 --port 8888 \
  --command upload \
  --local /var/log/application \
  --remote /backup/logs/application
```

**결과**: 서버 B의 `/var/log/application/` 전체 → 서버 A의 `/backup/logs/application/`

### 3. 서버 A → 서버 B로 파일 다운로드

#### 단일 파일 다운로드
```bash
# 서버 B에서 실행
python file_transfer.py --mode client --host 192.168.1.100 --port 8888 \
  --command download \
  --remote /backup/important.txt \
  --local /home/user/downloaded_important.txt
```

**결과**: 서버 A의 `/backup/important.txt` → 서버 B의 `/home/user/downloaded_important.txt`

#### 디렉토리 다운로드
```bash
# 서버 B에서 실행
python file_transfer.py --mode client --host 192.168.1.100 --port 8888 \
  --command download \
  --remote /backup/database \
  --local /restore/database
```

**결과**: 서버 A의 `/backup/database/` 전체 → 서버 B의 `/restore/database/`

## 실용적인 사용 케이스

### 1. 데이터베이스 백업 전송
```bash
# 백업 서버에서 DB 서버로부터 백업 파일 다운로드
python file_transfer.py --mode client --host db-server.company.com \
  --command download \
  --remote /var/backups/mysql/daily_backup.sql.gz \
  --local /backups/db/mysql_$(date +%Y%m%d).sql.gz
```

### 2. 로그 파일 수집
```bash
# 로그 수집 서버에서 웹 서버의 로그 수집
python file_transfer.py --mode client --host web-server-01.company.com \
  --command download \
  --remote /var/log/nginx \
  --local /logs/web-server-01/nginx
```

### 3. 코드 배포
```bash
# 빌드 서버에서 프로덕션 서버로 배포
python file_transfer.py --mode client --host prod-server-01.company.com \
  --command upload \
  --local /builds/app-v1.2.3 \
  --remote /opt/applications/app
```

### 4. 설정 파일 동기화
```bash
# 중앙 설정 서버에서 각 서버로 설정 배포
python file_transfer.py --mode client --host config-server.company.com \
  --command download \
  --remote /configs/nginx/nginx.conf \
  --local /etc/nginx/nginx.conf
```

## 🔒 보안 고려사항

### 1. 네트워크 보안
```bash
# SSH 터널을 통한 안전한 전송
ssh -L 8888:localhost:8888 user@target-server
# 그 후 localhost:8888로 연결
```

### 2. 방화벽 설정
```bash
# 서버 A에서 특정 포트 열기
sudo ufw allow 8888/tcp
sudo firewall-cmd --add-port=8888/tcp --permanent
```

### 3. 접근 제한
```bash
# 특정 IP에서만 접근 허용
python file_transfer.py --mode server --host 192.168.1.100 --port 8888
```

## 🚀 고성능 전송 팁

### 1. 압축 레벨 조정
```bash
# 네트워크가 느린 환경: 높은 압축
python file_transfer.py --mode server --compression-level 22

# 네트워크가 빠른 환경: 낮은 압축 (빠른 속도)
python file_transfer.py --mode server --compression-level 1
```

### 2. 동시 연결 수 증가
```bash
# 여러 파일을 병렬로 전송
for file in *.dat; do
  python file_transfer.py --mode client --host $TARGET_SERVER \
    --command upload --local "$file" --remote "/backup/$file" &
done
wait
```

### 3. 네트워크 최적화
```bash
# TCP 버퍼 크기 증가
echo 'net.core.rmem_max = 134217728' >> /etc/sysctl.conf
echo 'net.core.wmem_max = 134217728' >> /etc/sysctl.conf
sysctl -p
``` 