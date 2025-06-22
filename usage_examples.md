# 사용법 예시

## 기본 사용법

### 서버 시작
```bash
# 로컬 서버 (개발/테스트용)
python file_transfer.py server

# 원격 접속 허용 서버
python file_transfer.py server --host 0.0.0.0 --port 8834
```

### 파일 전송
```bash
# 단일 파일 업로드
python file_transfer.py upload /path/to/file.txt remote/file.txt

# 단축 명령어
python file_transfer.py up file.txt remote/file.txt

# 원격 서버로 전송
python file_transfer.py upload file.txt remote/file.txt --host 192.168.1.100
```

### 디렉토리 전송
```bash
# 디렉토리 전체 업로드 (재귀적)
python file_transfer.py upload /path/to/directory remote/directory

# 프로젝트 백업
python file_transfer.py up ./my_project backup/my_project_$(date +%Y%m%d)
```

## 실제 서버 간 전송 예시

### 예시 1: 웹사이트 배포
```bash
# 배포 서버에서 (20.20.2.155)
python file_transfer.py server --host 0.0.0.0 --port 8834

# 개발 서버에서 (20.20.2.156)
python file_transfer.py upload ./website_build production/website --host 20.20.2.155 --port 8834
```

### 예시 2: 데이터베이스 백업
```bash
# 백업 서버
python file_transfer.py server --port 8834

# 운영 서버
python file_transfer.py upload /backup/database_$(date +%Y%m%d).sql remote/backups/database_$(date +%Y%m%d).sql --host backup.company.com
```

### 예시 3: 로그 파일 수집
```bash
# 중앙 로그 서버
python file_transfer.py server --host 0.0.0.0 --port 8834

# 각 웹 서버에서
python file_transfer.py upload /var/log/nginx logs/web1/nginx_$(date +%Y%m%d) --host log.company.com
python file_transfer.py upload /var/log/apache2 logs/web2/apache_$(date +%Y%m%d) --host log.company.com
```

## 고급 사용법

### 대용량 파일 전송
```bash
# 30GB 데이터 파일 전송
python file_transfer.py upload /data/large_dataset.tar remote/datasets/large_dataset.tar --host data.company.com
```

### 개발 환경 동기화
```bash
# 개발 서버 동기화
python file_transfer.py upload ./source_code remote/projects/myapp --host dev.company.com

# 설정 파일 동기화
python file_transfer.py upload ./config remote/config/myapp --host dev.company.com
```

### 배치 스크립트 예시
```bash
#!/bin/bash
# backup_script.sh

SERVER="backup.company.com"
DATE=$(date +%Y%m%d)

# 데이터베이스 백업
python file_transfer.py upload /backup/db_${DATE}.sql remote/backups/db_${DATE}.sql --host $SERVER

# 웹 파일 백업
python file_transfer.py upload /var/www/html remote/backups/www_${DATE} --host $SERVER

# 로그 백업
python file_transfer.py upload /var/log remote/backups/logs_${DATE} --host $SERVER

echo "백업 완료: $DATE"
```

## 성능 최적화 팁

### 1. 네트워크 최적화
```bash
# 기가비트 네트워크에서 최적 포트 사용
python file_transfer.py server --port 8834

# 전용 포트로 분산 처리
python file_transfer.py server --port 8835  # 서버 2
python file_transfer.py server --port 8836  # 서버 3
```

### 2. 병렬 전송 (여러 파일)
```bash
# 백그라운드 병렬 전송
python file_transfer.py upload file1.txt remote/file1.txt --host server1 &
python file_transfer.py upload file2.txt remote/file2.txt --host server2 &
python file_transfer.py upload file3.txt remote/file3.txt --host server3 &
wait
```

## 모니터링 및 디버깅

### 서버 상태 확인
```bash
# 서버 실행 확인
ps aux | grep file_transfer.py

# 포트 사용 확인
netstat -tlnp | grep :8834

# 서버 로그 실시간 확인
tail -f server.log
```

### 네트워크 연결 테스트
```bash
# 기본 연결 테스트
telnet server_ip 8834

# 방화벽 확인 (Ubuntu/Debian)
sudo ufw status

# 방화벽 확인 (CentOS/RHEL)
sudo firewall-cmd --list-ports
```

## 자동화 예시

### cron 작업으로 정기 백업
```bash
# crontab -e
# 매일 새벽 2시에 백업
0 2 * * * /usr/bin/python /path/to/file_transfer.py upload /data/important remote/daily_backup_$(date +\%Y\%m\%d) --host backup.server.com
```

### systemd 서비스로 서버 자동 시작
```ini
# /etc/systemd/system/file-transfer.service
[Unit]
Description=File Transfer Server
After=network.target

[Service]
Type=simple
User=filetransfer
WorkingDirectory=/opt/file-transfer
ExecStart=/usr/bin/python file_transfer.py server --host 0.0.0.0 --port 8834
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# 서비스 활성화
sudo systemctl enable file-transfer
sudo systemctl start file-transfer
sudo systemctl status file-transfer
```

## 보안 고려사항

### 방화벽 설정
```bash
# Ubuntu/Debian
sudo ufw allow 8834/tcp

# CentOS/RHEL
sudo firewall-cmd --permanent --add-port=8834/tcp
sudo firewall-cmd --reload
```

### SSH 터널 사용 (보안 강화)
```bash
# SSH 터널 생성
ssh -L 8834:localhost:8834 user@remote_server

# 로컬 연결로 전송 (암호화됨)
python file_transfer.py upload file.txt remote/file.txt --host localhost --port 8834
```

## 문제 해결

### 일반적인 오류와 해결법

1. **연결 거부 오류**
   ```bash
   # 서버가 실행 중인지 확인
   python file_transfer.py server --host 0.0.0.0 --port 8834
   ```

2. **권한 오류**
   ```bash
   # 파일 권한 확인
   ls -la /path/to/file
   chmod 644 /path/to/file
   ```

3. **디스크 공간 부족**
   ```bash
   # 디스크 공간 확인
   df -h
   ```

4. **포트 충돌**
   ```bash
   # 다른 포트 사용
   python file_transfer.py server --port 8835
   ``` 