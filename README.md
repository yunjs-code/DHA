# UAV Security Testbed

실제 전장의 드론-지휘소(GCS) 통신 구조를 재현한 보안 연구용 테스트베드.

---

## 목차

1. [개요](#개요)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [파일 구조](#파일-구조)
4. [실행 방법](#실행-방법)
   - [방법 A — Docker (권장)](#방법-a--docker-권장)
   - [방법 B — Linux VM (VirtualBox)](#방법-b--linux-vm-virtualbox)
5. [코드 수정 방법](#코드-수정-방법)
6. [실험 방법](#실험-방법)
7. [WebSocket / REST API 스키마](#websocket--rest-api-스키마)
8. [포트 정보](#포트-정보)

---

## 개요

| 화면 | 역할 |
|------|------|
| **GCS** (`/gcs/`) | 드론 실시간 위치 지도 + ARM / TAKEOFF / GOTO 등 명령 전송 |
| **Attacker** (`/attacker/`) | GCS ↔ 드론 사이를 오가는 MAVLink 바이너리 패킷 실시간 스니핑 |

핵심 특징:
- 서버 ↔ SITL 구간은 **MAVLink v2 바이너리 전용** (JSON 금지)
- 브라우저 ↔ 서버 구간은 **WebSocket JSON**
- ArduPilot ArduCopter **실제 FC 펌웨어**를 소프트웨어(SITL)로 실행

---

## 시스템 아키텍처

```
[브라우저]
  ├─ GCS 화면     ─── WebSocket JSON ──┐
  └─ Attacker 화면─── WebSocket JSON ──┤
                                       │
                               [FastAPI 서버]  ← app/main.py
                                       │
                          MAVLink v2 바이너리 (TCP)
                                       │
                    ┌──────────────────┼──────────────────┐
               [SITL drone-01]  [SITL drone-02]  [SITL drone-03]
                 TCP :5760         TCP :5770         TCP :5780
```

### 데이터 흐름

```
드론 → SITL → [app/sitl.py: pymavlink recv]
            → [app/mavlink.py: 바이너리 디코딩]
            → [app/main.py: 20Hz 브로드캐스트]
            → GCS WebSocket (telemetry JSON)
            → Attacker WebSocket (hex + fields JSON)

GCS 브라우저 → POST /api/command
            → [app/mavlink.py: COMMAND_LONG 인코딩]
            → [app/sitl.py: pymavlink TCP 전송]
            → SITL 드론
            → Attacker WebSocket에도 미러링 (direction: "up")
```

---

## 파일 구조

```
uav-security-testbed/
│
├── app/
│   ├── main.py       ← FastAPI 앱, WebSocket 허브, 20Hz 브로드캐스트 루프
│   ├── mavlink.py    ← MAVLink v2 바이너리 인코딩·디코딩 (순수 함수)
│   └── sitl.py       ← SITLConnector: pymavlink TCP 연결·송수신
│
├── frontend/
│   ├── gcs/
│   │   └── index.html  ← 지도(Leaflet) + 명령 UI + 명령 로그
│   └── attacker/
│       └── index.html  ← 패킷 스트림 뷰어 (hex + 필드 파싱)
│
├── scripts/
│   ├── restart.sh          ← VM 환경: SITL 3대 + 서버 재시작
│   ├── start_sitl.sh       ← VM 환경: SITL만 기동 (sim_vehicle.py 방식)
│   ├── docker_sitl_start.sh← Docker 환경: SITL 3대 기동
│   └── inject_attack.py    ← 공격 스크립트 (FastAPI 우회, SITL 직접 접속)
│
├── terrain/
│   ├── N37E126.DAT   ← 서울 지형 데이터 (ArduPilot TERRAIN 기능)
│   └── N37E127.DAT
│
├── sitl_params.parm  ← SITL 필수 파라미터 (pre-arm 체크 비활성화 등)
├── requirements.txt
├── Dockerfile        ← FastAPI 서버 이미지
├── Dockerfile.sitl   ← ArduPilot SITL 이미지 (소스 빌드 포함)
└── docker-compose.yml
```

---

## 실행 방법

### 방법 A — Docker (권장)

**사전 조건**: Docker Desktop 설치 (Windows / Mac / Linux 동일)

```bash
git clone git@github.com:yunjs-code/DHA.git
cd DHA
docker compose up --build
```

- **첫 실행**: ArduPilot 소스 빌드 포함 → 약 30~60분
- **이후 실행**: `docker compose up` (캐시 활용, 수초 내 시작)

접속:
- GCS: `http://localhost:8000/gcs/`
- Attacker: `http://localhost:8000/attacker/`

---

### 방법 B — Linux VM (VirtualBox)

#### VM 구성

| 항목 | 값 |
|------|----|
| OS | Ubuntu 22.04 |
| 네트워크 | Host-Only 어댑터, IP `192.168.56.101` |
| 공유폴더 | Windows 프로젝트 폴더 → VM `/media/sf_uav` (자동 마운트) |

#### VM 초기 셋업

```bash
# ArduPilot 빌드 (최초 1회)
git clone https://github.com/ArduPilot/ardupilot.git ~/ardupilot
cd ~/ardupilot
git submodule update --init --recursive
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
./waf configure --board sitl
./waf copter

# 서울 위치 등록
echo "Seoul=37.5665,126.9780,0,0" >> ~/ardupilot/Tools/autotest/locations.txt

# Python 가상환경 + 패키지
python3 -m venv ~/venv-ardupilot
source ~/venv-ardupilot/bin/activate
pip install -r /media/sf_uav/requirements.txt
```

#### 매 세션 실행

```bash
source ~/venv-ardupilot/bin/activate
cd /media/sf_uav
bash scripts/restart.sh
```

`restart.sh`가 자동으로:
1. SITL 3대 기동 (TCP 5760 / 5770 / 5780)
2. FastAPI 서버 시작 (`uvicorn --reload`)

접속:
- GCS: `http://192.168.56.101:8000/gcs/`
- Attacker: `http://192.168.56.101:8000/attacker/`

---

## 코드 수정 방법

### Docker 환경

파일을 로컬에서 수정하면 **uvicorn이 자동 재시작**합니다. 브라우저만 새로고침하면 됩니다.

```
로컬 app/ 또는 frontend/ 파일 수정
    → docker-compose 볼륨 마운트로 컨테이너에 즉시 반영
    → uvicorn --reload 자동 재시작
    → 브라우저 새로고침으로 확인
```

> **주의**: `requirements.txt`를 바꿀 때는 `docker compose up --build` 필요.

### VM 환경

```
Windows에서 파일 수정·저장
    → VirtualBox 공유폴더가 VM /media/sf_uav 에 즉시 동기화
    → uvicorn --reload 자동 재시작
    → 브라우저 새로고침 (Ctrl+Shift+R 강력 새로고침 권장)
```

### 수정 가능한 파일 역할

| 파일 | 수정하면 |
|------|---------|
| `app/main.py` | 브로드캐스트 주기, REST 엔드포인트, WebSocket 메시지 형식 변경 |
| `app/mavlink.py` | 지원하는 MAVLink 메시지 타입 추가/변경, 인코딩 방식 변경 |
| `app/sitl.py` | 연결 드론 수, 재연결 타임아웃, 텔레메트리 파싱 로직 변경 |
| `frontend/gcs/index.html` | GCS UI 레이아웃, 지도, 명령 버튼, 로그 형식 변경 |
| `frontend/attacker/index.html` | Attacker UI, 패킷 필터, 표시 형식 변경 |
| `sitl_params.parm` | SITL 드론 파라미터 (ARM 조건, EKF 설정 등) |

---

## 실험 방법

### 1. GCS 화면에서 드론 조작

1. `http://<서버>/gcs/` 접속
2. 드론 카드 클릭 → 선택 (복수 선택 가능)
3. 명령 전송:

| 버튼 | 동작 |
|------|------|
| ARM | 드론 시동 |
| DISARM | 시동 끄기 |
| TAKEOFF | 이륙 (기본 30m) |
| LAND | 현위치 착륙 |
| RTL | 홈 복귀 |
| GOTO | 지도 클릭 위치로 이동 |
| SET_MODE | 비행 모드 변경 |

> GOTO: 지도를 클릭하면 위도/경도 자동 입력됨

### 2. Attacker 화면에서 패킷 분석

`http://<서버>/attacker/` 접속

- **↓ down**: 드론 → GCS 방향 패킷 (텔레메트리, HEARTBEAT 등)
- **↑ up**: GCS → 드론 방향 패킷 (명령, COMMAND_LONG)
- 드론별·메시지 타입별 필터 가능
- 각 패킷: `msg_name`, `hex` (원본 바이너리), 파싱된 필드 표시

### 3. 공격 스크립트 (FastAPI 우회)

`scripts/inject_attack.py`는 FastAPI를 통하지 않고 SITL TCP 포트에 **직접** 접속하여 명령을 주입합니다.

```bash
# 단일 명령 주입
python scripts/inject_attack.py --drone drone-01 --cmd ARM
python scripts/inject_attack.py --drone drone-01 --cmd TAKEOFF --alt 30
python scripts/inject_attack.py --drone drone-01 --cmd GOTO --lat 37.570 --lon 126.982 --alt 50
python scripts/inject_attack.py --drone drone-01 --cmd LAND

# 전체 공격 시퀀스 (GUIDED → ARM → TAKEOFF → GOTO 자동 실행)
python scripts/inject_attack.py --drone drone-02 --cmd SEQUENCE --lat 37.570 --lon 126.982 --alt 30
```

> **동작 원리**: 공격자가 같은 네트워크에 있을 때 SITL TCP 포트(5760/5770/5780)에 직접 접속 가능. FastAPI 인증·검증을 완전히 우회.
> GCS 화면에서 드론 상태 변화로 공격 성공 여부 확인.

---

## WebSocket / REST API 스키마

### `/ws/gcs` — GCS 브라우저 수신

```jsonc
// 텔레메트리 (20Hz)
{
  "type": "telemetry",
  "drone_id": "drone-01",
  "lat": 37.5665, "lon": 126.9780,
  "alt": 100.0,          // 절대고도 (m)
  "relative_alt": 50.0,  // 홈 기준 상대고도 (m)
  "groundspeed": 5.2,
  "heading": 270,
  "battery_pct": 87.0,
  "armed": true,
  "mode": "GUIDED",
  "connected": true,
  "ekf_ok": true
}

// 명령 ACK
{
  "type": "cmd_ack",
  "drone_id": "drone-01",
  "cmd": "ARM/DISARM",
  "result": "ACCEPTED"   // ACCEPTED | TEMPORARILY_REJECTED | DENIED | UNSUPPORTED | FAILED
}
```

### `/ws/attacker` — Attacker 브라우저 수신

```jsonc
{
  "type": "packet",
  "direction": "down",      // "down"=드론→GCS | "up"=GCS→드론
  "drone_id": "drone-01",
  "msg_id": 33,
  "msg_name": "GLOBAL_POSITION_INT",
  "hex": "fd1c000000...",   // MAVLink v2 원본 바이너리 (소문자 hex)
  "fields": {
    "lat": 37.5665,
    "lon": 126.9780,
    "alt": 100.0
  }
}
```

### `POST /api/command`

```jsonc
// 요청
{ "drone_id": "drone-01", "cmd": "ARM",     "params": {} }
{ "drone_id": "drone-01", "cmd": "TAKEOFF", "params": { "alt": 30 } }
{ "drone_id": "drone-01", "cmd": "GOTO",    "params": { "lat": 37.5, "lon": 126.9, "alt": 30 } }
{ "drone_id": "drone-01", "cmd": "SET_MODE","params": { "mode": "GUIDED" } }

// 응답
{ "status": "sent", "drone_id": "drone-01", "cmd": "ARM" }
```

### `GET /api/drones`

```jsonc
{
  "drone-01": { "connected": true,  "ready": true  },
  "drone-02": { "connected": false, "ready": false },
  "drone-03": { "connected": true,  "ready": true  }
}
```

---

## 포트 정보

| 용도 | 포트 | 프로토콜 |
|------|------|---------|
| FastAPI HTTP/WS | 8000 | TCP |
| SITL drone-01 | 5760 | TCP |
| SITL drone-02 | 5770 | TCP |
| SITL drone-03 | 5780 | TCP |

### 드론 비행 모드 번호 (ArduCopter)

| 번호 | 모드 |
|------|------|
| 0 | STABILIZE |
| 3 | AUTO |
| 4 | GUIDED |
| 5 | LOITER |
| 6 | RTL |
| 9 | LAND |

---

## 스택

| 구성 요소 | 기술 |
|----------|------|
| 백엔드 | Python 3.11, FastAPI, pymavlink |
| 프론트엔드 | Vanilla JS, Leaflet.js (빌드 도구 없음) |
| SITL | ArduPilot ArduCopter (실제 FC 펌웨어) |
| 컨테이너 | Docker + docker-compose |
