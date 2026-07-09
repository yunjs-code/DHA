# UAV Security Testbed — 실행 가이드

## 시스템 구성

```
[Windows 호스트 192.168.56.1]
  └─ 브라우저
       ├─ GCS   http://192.168.56.101:8000/gcs/
       └─ Attacker http://192.168.56.101:8000/attacker/

[Linux VM 192.168.56.101 "drone-server"]
  ├─ ArduCopter SITL × 3  (TCP 5760 / 5770 / 5780)
  │    drone-01/02/03 모두 --model quad (ArduCopter 내장 물리 모델, 외부 FDM 불필요)
  ├─ Python TCP 릴레이 × 3  (스크립트: scripts/mavlink_tcp_relay.py)
  │    drone-01: 5760 → 15760 (서버용) / 25760 (공격용)
  │    drone-02: 5770 → 15770 (서버용) / 25770 (공격용)
  │    drone-03: 5780 → 15780 (서버용) / 25780 (공격용)
  └─ FastAPI 서버  (TCP 8000)
       ├─ /ws/gcs      → GCS 브라우저에 텔레메트리 브로드캐스트 (20 Hz)
       ├─ /ws/attacker → Attacker 브라우저에 패킷 스트림 브로드캐스트
       ├─ POST /api/command → SITL에 MAVLink COMMAND_LONG 전송
       ├─ GET  /api/drones  → 드론 연결 상태
       └─ GET  /api/debug   → 연결 진단 정보
```

### 통신 흐름

```
브라우저 ──WS JSON──▶ FastAPI ──MAVLink binary──▶ TCP 릴레이 ──▶ ArduCopter 
                                   ◀────────────────────────────────
```

> MAVProxy 없이 자체 Python TCP 릴레이(`mavlink_tcp_relay.py`) 사용.  
> ArduCopter 1대당 릴레이 1개가 서버용/공격용 포트 2개를 동시에 서빙.

---

## 포트 정리

| 드론 | ArduCopter 내부 | 서버 접속 | 공격 스크립트 접속 |
|------|:-----------:|:---------:|:----------:|
| drone-01 | TCP 5760 | TCP 15760 | TCP 25760 |
| drone-02 | TCP 5770 | TCP 15770 | TCP 25770 |
| drone-03 | TCP 5780 | TCP 15780 | TCP 25780 |
| FastAPI  | —        | TCP 8000  | — |

---

## 매 세션 실행 순서

### 1단계 — 전체 스택 시작 (단일 명령)

```bash
source ~/venv-ardupilot/bin/activate
cd /media/sf_uav
bash scripts/start_sitl.sh
```

스크립트가 자동으로 수행하는 일:
1. 기존 arducopter / mavlink_tcp_relay / uvicorn 프로세스 정리
2. ArduCopter SITL 3대 순서대로 직접 실행 (바이너리: `~/ardupilot/build/sitl/bin/arducopter`,
   `--model quad` — 내장 물리 모델, 외부 FDM 불필요)
3. 각 ArduCopter TCP 포트 오픈 확인 (최대 40초 대기, 실패 시 즉시 보고)
4. Python TCP 릴레이 3개 실행 → 포트 15760·25760 등 개설 (최대 10초 대기, 실패 시 즉시 보고)
5. 드론 중 하나라도 실패하면 실패 목록을 출력하고 `exit 1` (서버는 기동하지 않음)
6. 3대 모두 성공하면 마지막으로 `uvicorn app.main:app`를 같은 터미널에서 그대로 실행
   (Ctrl+C 한 번으로 SITL·릴레이·서버 전체 종료)

> **정상 출력 예시**
> ```
> [STEP] drone-01: ArduCopter 시작 (TCP:5760, model=quad)
>        TCP:5760 오픈 대기   ✔ OK (1초)
>        릴레이 시작: TCP:5760 → SERVER:15760 / ATTACK:25760
>        SERVER:15760 / ATTACK:25760 오픈 대기   ✔ OK (1초)
> ...
> [INFO] 3대 SITL + 릴레이 정상 기동 완료
> [INFO] FastAPI 서버 시작 (Ctrl+C로 전체 종료)
> ```
> **실패 시**: 실패한 드론 목록과 확인할 로그 경로가 출력되고 스크립트가 `exit 1`로 종료된다
> (서버는 기동되지 않으므로, 브라우저에서 원인 모른 채 헤매는 상황을 방지).

---

### 2단계 — 브라우저 접속

| 화면 | URL |
|------|-----|
| GCS (지도 + 명령 UI) | http://192.168.56.101:8000/gcs/ |
| Attacker (패킷 스트림) | http://192.168.56.101:8000/attacker/ |
| 연결 진단 | http://192.168.56.101:8000/api/debug |

---

## 종료

`scripts/start_sitl.sh`를 실행한 터미널에서 Ctrl+C 한 번이면 SITL·릴레이·서버가 모두 종료된다.
프로세스가 남아있다면 수동으로:

```bash
pkill -f uvicorn
pkill -f arducopter
pkill -f mavlink_tcp_relay
```

---

## 공격 시나리오

### §3.3 MAVLink 서명 방어 실험

#### 사전 준비 — 서명 키 생성 (최초 1회)

```bash
python3 scripts/generate_key.py        # signing.key 생성
```

#### A. 방어 전 공격 (무서명 → ACCEPTED)

```bash
# Windows 또는 VM에서 실행
python3 scripts/inject_attack.py --drone drone-01 --cmd ARM --no-sign
```

기대 결과: `COMMAND_ACK: ARM → ACCEPTED` (방어 없으므로 통과)

#### B. 서명 방어 활성화

```bash
python3 scripts/defense_signing.py --drone drone-01 --key-file signing.key
```

#### C. 방어 후 무서명 공격 → 묵살 확인

```bash
python3 scripts/inject_attack.py --drone drone-01 --cmd ARM --no-sign
```

기대 결과: ACK 없음 (5초 타임아웃) — 무서명 패킷 묵살

#### D. 키 탈취 후 서명 공격 → ACCEPTED

```bash
python3 scripts/inject_attack.py --drone drone-01 --cmd ARM --sign --key-file signing.key
```

기대 결과: `COMMAND_ACK: ARM → ACCEPTED`

#### 전체 공격 시퀀스 (GUIDED → ARM → TAKEOFF → GOTO)

```bash
python3 scripts/inject_attack.py \
    --drone drone-01 --cmd SEQUENCE \
    --lat 37.5700 --lon 126.9800 --alt 30
```

---

## 디버그 명령

### 연결 상태 확인

```bash
# 포트 오픈 여부
ss -tlnp | grep -E '5760|5770|5780|15760|15770|15780'

# FastAPI 진단 엔드포인트
curl http://127.0.0.1:8000/api/debug | python3 -m json.tool
```

`/api/debug` 응답 항목:

| 필드 | 의미 |
|------|------|
| `tcp_open` | 서버 포트(15760 등)에 TCP 연결 가능 여부 |
| `ready` | HEARTBEAT 수신 완료 여부 |
| `connect_attempts` | 연결 시도 횟수 |
| `last_error` | 마지막 오류 메시지 |
| `last_recv_secs_ago` | 마지막 패킷 수신 경과 시간 (초) |

### 로그 실시간 확인

```bash
# ArduCopter 로그
tail -f /tmp/arducopter_drone-01.log

# TCP 릴레이 로그
tail -f /tmp/mavproxy_drone-01.log

# FastAPI 로그 → start_sitl.sh 실행 터미널에서 확인
```

### 프로세스 확인

```bash
ps aux | grep -E 'arducopter|mavlink_tcp_relay|uvicorn'
```

---

## 트러블슈팅

### 증상: `Address already in use` (포트 8000)

```bash
pkill -f uvicorn ; sleep 1
bash scripts/start_sitl.sh
```

### 증상: SITL 포트(15760 등)가 안 열림

```bash
# 릴레이 로그 확인
cat /tmp/mavproxy_drone-01.log

# ArduCopter가 살아있는지 확인
ss -tlnp | grep 5760

# 전체 재시작
pkill -f arducopter ; pkill -f mavlink_tcp_relay ; sleep 2
bash scripts/start_sitl.sh
```

### 증상: FastAPI가 HEARTBEAT를 받지 못함 (`connect_attempts` 증가)

```bash
# 릴레이가 ArduCopter에 연결됐는지 확인
cat /tmp/mavproxy_drone-01.log
# 정상: "[RELAY] ✔ ArduCopter 연결: 127.0.0.1:5760"
# 오류: "[RELAY] ✗ ArduCopter 연결 실패"
```

### 증상: ArduCopter 바이너리 없음

```bash
cd ~/ardupilot
./waf configure --board sitl
./waf copter
```

### 증상: 드론이 이륙하지 못함 (EKF/GPS 미수렴)

```bash
# --model quad는 외부 FDM 없이 즉시 GPS/EKF가 수렴해야 정상.
# 로그에서 EKF 상태 확인:
cat /tmp/arducopter_drone-01.log | grep -i ekf

# GCS 화면에서 ekf_ok=false로 계속 남아있다면 SITL을 완전히 재시작:
pkill -f arducopter ; pkill -f mavlink_tcp_relay ; sleep 2
bash scripts/start_sitl.sh
```

---

## 파일 구조

```
app/
├── main.py      FastAPI 앱, WebSocket 허브, 브로드캐스트 루프 (20 Hz)
├── mavlink.py   MAVLink v2 바이너리 인코딩·디코딩 (순수 함수)
└── sitl.py      SITLConnector — pymavlink TCP 수신·송신

frontend/
├── gcs/
│   └── index.html  지도 + 명령 UI
└── attacker/
    └── index.html  패킷 스트림 뷰어 (hex + 파싱값, 드론/타입 필터)

scripts/
├── start_sitl.sh          SITL 3대 + 릴레이 + FastAPI 서버 전체 기동 (단일 명령)
├── mavlink_tcp_relay.py   TCP 릴레이 (MAVProxy 대체, select 기반)
├── generate_key.py        32바이트 서명 키 생성
├── defense_signing.py     §3.3 서명 방어 활성화
└── inject_attack.py       §3.3 공격 주입 (--sign / --no-sign)
```

---

## 환경 정보

| 항목 | 값 |
|------|----|
| VM IP | 192.168.56.101 |
| Windows IP | 192.168.56.1 |
| Python 가상환경 | `~/venv-ardupilot` |
| ArduPilot 경로 | `~/ardupilot` |
| 코드 공유 경로 | `/media/sf_uav` (VirtualBox 공유폴더, 자동 동기화) |
| ArduCopter 홈 | 서울 (lat=37.566535, lon=126.977969) |
