# UAV Security Testbed — 구현 계획

## 구현 순서 원칙
하위 의존성부터 구현. 테스트 가능한 단위로 쪼개서 진행.
```
Phase 0: 환경 구성 (VM + 공유폴더 + 패키지)
Phase 1: mavlink.py  →  Phase 2: sitl.py  →  Phase 3: main.py
Phase 4: frontend/gcs/  →  Phase 5: frontend/attacker/
```

---

## Phase 0 — 환경 구성 (코드 작성 전 1회만 수행)

### 0-1. 머신 구성 및 역할

이 프로젝트는 **물리 머신 1대 + VirtualBox VM 1대** 로 동작한다.

| 머신 | OS | IP | 역할 |
|------|----|----|------|
| **Windows 호스트** | Windows 11 | `192.168.56.1` (Host-Only) | 코드 작성(VS Code/Claude), 브라우저(GCS·Attacker 화면) |
| **Linux VM** `drone-server` | Ubuntu 22.04 | `192.168.56.101` (Host-Only) | ArduPilot SITL 실행, FastAPI 서버 실행 |

```
[Windows 호스트 192.168.56.1]
  ├── VS Code / Claude Code   ← 코드 작성
  ├── Chrome 브라우저          ← http://192.168.56.101:8000/gcs
  └── C:\...\uav-security-testbed\   ←──┐
                                    VirtualBox 공유폴더 (실시간 동기화)
[Linux VM: drone-server 192.168.56.101]  │
  ├── /media/sf_uav/          ←──────────┘  (같은 파일을 바라봄)
  ├── uvicorn app.main:app    ← FastAPI 서버 (포트 8000)
  ├── ArduPilot SITL ×3       ← 드론 시뮬레이터 (UDP 14560/14570/14580)
  └── ~/ardupilot/            ← ArduPilot 소스·빌드
```

### 0-2. 코드 동기화 방식 (공유폴더 — 별도 전송 불필요)

VirtualBox 공유폴더를 사용하므로 **파일 복사나 git push 없이** Windows에서 저장하면 VM에서 즉시 반영된다.

```
Windows에서 파일 저장
    ↓ (VirtualBox 공유폴더 자동 동기화)
VM /media/sf_uav/ 에서 즉시 동일 파일 반영
    ↓
VM에서 uvicorn 재시작만 하면 최신 코드 동작
```

**VM에서 서버 재시작 방법:**
```bash
# /media/sf_uav 에서 실행
pkill -f uvicorn
source ~/venv-ardupilot/bin/activate
cd /media/sf_uav
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
`--reload` 플래그를 쓰면 파일 변경 시 자동 재시작 (개발 중 권장).

### 0-3. VirtualBox VM 설정 확인

**필수 VM 사양:**
| 항목 | 권장값 |
|------|--------|
| OS | Ubuntu 22.04 LTS (64-bit) |
| RAM | 4 GB 이상 |
| CPU | 2코어 이상 |
| 네트워크 어댑터1 | NAT (인터넷 접속용) |
| 네트워크 어댑터2 | Host-Only Adapter → `VirtualBox Host-Only Ethernet Adapter` |

**Host-Only 어댑터 IP 확인 (VM 터미널):**
```bash
ip addr show        # enp0s8 등에서 192.168.56.101 확인
ping 192.168.56.1   # Windows 호스트와 통신 확인
```

### 0-4. VirtualBox 공유폴더 설정 확인
VirtualBox 설정 > 공유폴더에 아래 항목이 있어야 한다:

| 항목 | 값 |
|------|----|
| 폴더 경로 (호스트) | `C:\Users\wsx03\Downloads\uav-security-testbed (1)\uav-security-testbed` |
| 폴더 이름 | `uav` (또는 임의) |
| 마운트 지점 (VM) | `/media/sf_uav` |
| 자동 마운트 | ✓ |
| 영구적 설정 | ✓ |

VM 터미널에서 확인:
```bash
ls /media/sf_uav        # CLAUDE.md, PLAN.md 등이 보여야 함
groups | grep vboxsf    # vboxsf 그룹 포함 여부 확인
```
그룹 없으면:
```bash
sudo usermod -aG vboxsf vboxuser
newgrp vboxsf
```

### 0-5. Python 환경 확인
```bash
# ArduPilot venv 활성화 (매 세션마다 실행)
source ~/venv-ardupilot/bin/activate

# 필요 패키지 확인
pip show fastapi uvicorn pymavlink aiofiles | grep -E "Name|Version"
```

패키지 없으면 설치:
```bash
cd /media/sf_uav
pip install -r requirements.txt
```

### 0-6. ArduPilot SITL 빌드 확인
```bash
ls ~/ardupilot/build/sitl/bin/arducopter   # 파일 존재해야 함
which sim_vehicle.py                        # 경로 확인
```

빌드 안 된 경우:
```bash
cd ~/ardupilot
./waf configure --board sitl
./waf copter
```

### 0-7. Seoul 위치 등록 (최초 1회)
SITL이 서울에서 시작하도록 위치 파일에 추가:
```bash
echo "Seoul=37.566535,126.977969,0,0" >> ~/ardupilot/Tools/autotest/locations.txt
```

이미 있으면 무시 (중복 등록해도 문제 없음):
```bash
grep Seoul ~/ardupilot/Tools/autotest/locations.txt
```

### 0-8. 환경 구성 완료 체크리스트
```
[ ] ls /media/sf_uav          → CLAUDE.md, PLAN.md 보임
[ ] ip addr → enp0s8에서 192.168.56.101 확인
[ ] ping 192.168.56.1         → Windows 호스트 응답 확인
[ ] groups | grep vboxsf      → vboxsf 그룹 포함
[ ] source ~/venv-ardupilot/bin/activate
[ ] pip show fastapi pymavlink → 설치 확인
[ ] ls ~/ardupilot/build/sitl/bin/arducopter → 파일 존재
[ ] grep Seoul ~/ardupilot/Tools/autotest/locations.txt → 등록 확인
```

모든 항목 통과 후 Phase 1로 진행.

---

## Phase 1 — MAVLink 바이너리 레이어 (`app/mavlink.py`)
**목적**: 서버↔SITL 구간의 핵심. 이것이 올바르지 않으면 전체가 무너진다.

### 구현 항목
- [x] MAVLink v2 패킷 헤더 파싱 (STX=0xFD, LEN, SEQ, SYSID, COMPID, MSGID)
- [x] HEARTBEAT(#0) 디코딩: type, autopilot, base_mode, custom_mode, system_status
- [x] SYS_STATUS(#1) 디코딩: battery_remaining
- [x] GLOBAL_POSITION_INT(#33) 디코딩: lat, lon, alt, vx, vy, hdg
- [x] VFR_HUD(#74) 디코딩: airspeed, groundspeed, heading, throttle, alt, climb
- [x] COMMAND_LONG(#76) 디코딩: target_system, command, params[0-6]
- [x] COMMAND_ACK(#77) 디코딩: command, result
- [x] `encode_command(drone_id, cmd, params) → bytes` 구현
  - ARM: command=400, param1=1.0
  - DISARM: command=400, param1=0.0
  - TAKEOFF: command=22, param7=alt
  - LAND: command=21
  - RTL: command=20
  - GOTO: command=192 (MAV_CMD_CONDITION_YAW) or DO_REPOSITION

### 검증 방법
```python
# 파이썬 REPL에서 직접 확인
raw = bytes.fromhex("fd09000000010000000000000600080000000000000006c801")
result = decode(raw)
assert result["msg_name"] == "HEARTBEAT"
```

---

## Phase 2 — SITL 커넥터 (`app/sitl.py`)
**목적**: pymavlink로 실제 ArduPilot SITL과 연결. 원본 바이너리를 보존.

### 구현 항목
- [x] `SITLConnector` 클래스 골격
- [x] `start()`: 백그라운드 스레드 시작
- [x] 수신 스레드: `mavutil.mavlink_connection('udpin:0.0.0.0:PORT')`
- [x] 수신 시 원본 바이너리 큐 (`_raw_queue: deque[bytes]`, maxlen=100)
- [x] 수신 시 파싱 상태 캐시 (`_state: dict`)
- [x] `recv_raw() → bytes | None`: 가장 최근 수신 바이너리 반환 (큐 소비 없음)
- [x] `drain_raw() → list[bytes]`: 큐 전체 소비 (브로드캐스터용)
- [x] `get_state() → dict`: 파싱된 최신 상태 반환
- [x] `send_command(raw: bytes)`: UDP로 SITL에 전송
- [x] `is_ready() → bool`: 첫 패킷 수신 여부

### 검증 방법
SITL 실행 후:
```bash
python3 -c "
from app.sitl import SITLConnector
c = SITLConnector('drone-01', 14560); c.start()
import time; time.sleep(3)
print(c.get_state())
"
```

---

## Phase 3 — FastAPI 서버 (`app/main.py`)
**목적**: WebSocket 허브. GCS와 Attacker 클라이언트에게 패킷 브로드캐스트.

### 구현 항목
- [x] FastAPI 앱 초기화, CORS 설정
- [x] `SITLConnector` 3개 인스턴스 생성 (drone-01~03, TCP 5760~5762)
- [x] `lifespan`: 커넥터 `start()` + 브로드캐스트 루프 시작
- [x] `/ws/gcs` WebSocket 엔드포인트
- [x] `/ws/attacker` WebSocket 엔드포인트
- [x] 브로드캐스트 루프 (asyncio 백그라운드 태스크, 20Hz)
  - `drain_raw()` → `mavlink.decode()` → GCS JSON + Attacker JSON 동시 전송
- [x] `GET /api/drones` REST: 연결 상태 반환
- [x] `POST /api/command` REST: 명령 수신 → encode → TCP 전송 → Attacker에 미러링
- [x] static 파일 서빙: `/gcs` → `frontend/gcs/`, `/attacker` → `frontend/attacker/`

### 브로드캐스트 메시지 포맷
```jsonc
// GCS용
{"type":"telemetry","drone_id":"drone-01","lat":37.5665,"lon":126.978,
 "alt":100.0,"speed_mps":5.2,"heading_deg":270.0,"battery_pct":85.0,
 "armed":true,"mode":"GUIDED"}

// Attacker용
{"type":"packet","direction":"down","drone_id":"drone-01",
 "msg_id":33,"msg_name":"GLOBAL_POSITION_INT",
 "hex":"fd1c000000...","fields":{"lat":37.5665,...}}

// 명령 ACK (GCS + Attacker 둘 다)
{"type":"cmd_ack","drone_id":"drone-01","cmd":"ARM","result":"ACCEPTED"}
```

### 검증 방법
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 브라우저에서 http://192.168.56.101:8000/gcs 접속 확인
```

---

## Phase 4 — GCS 화면 (`frontend/gcs/`)
**목적**: 드론 위치 지도 + 명령 전송 UI.

### 구현 항목
- [ ] `index.html`: 레이아웃 (지도 70%, 명령 패널, 로그)
- [ ] Leaflet 지도 초기화 (서울 중심, OSM 타일)
- [ ] WebSocket `/ws/gcs` 연결 + 자동 재연결
- [ ] `telemetry` 수신 → 드론 마커 위치 업데이트
- [ ] 마커 팝업: drone_id, alt, speed, battery, mode
- [ ] 드론 선택 드롭다운
- [ ] ARM / DISARM / TAKEOFF / LAND / RTL 버튼
- [ ] GOTO: 위도/경도 입력 → 전송
- [ ] `cmd_ack` 수신 → 명령 로그 추가 (색상 구분)
- [ ] 선택 드론 없으면 명령 버튼 disabled

### 검증 방법
브라우저에서 http://192.168.56.101:8000/gcs 접속:
- 드론 마커가 지도에 실시간으로 움직이는지 확인
- ARM 버튼 클릭 → 로그에 ACCEPTED 표시 확인

---

## Phase 5 — 공격자 화면 (`frontend/attacker/`)
**목적**: 실제 오가는 MAVLink 바이너리 패킷 실시간 표시.

### 구현 항목
- [ ] `index.html`: 패킷 스트림 레이아웃
- [ ] WebSocket `/ws/attacker` 연결 + 자동 재연결
- [ ] 패킷 렌더링: 방향(↑↓), drone_id, msg_name, hex, fields
- [ ] hex 표시: 소문자, 2자리씩 공백 (`fd 1c 00 ...`)
- [ ] 방향 색상: ↓초록(드론→GCS), ↑주황(GCS→드론)
- [ ] 드론 필터 (ALL / drone-01 / drone-02 / drone-03)
- [ ] 메시지 타입 필터 (ALL / HEARTBEAT / GLOBAL_POSITION_INT / ...)
- [ ] 일시정지 / 초기화 버튼
- [ ] 패킷 최대 200개 유지

### 검증 방법
브라우저에서 http://192.168.56.101:8000/attacker 접속:
- 패킷이 실시간으로 흘러내려가는지 확인
- GCS에서 ARM 명령 전송 → ↑ COMMAND_LONG 패킷 표시 확인

---

## 기타 파일
- [ ] `requirements.txt`: fastapi, uvicorn[standard], pymavlink, aiofiles
- [ ] `scripts/start_sitl.sh`: 3대 SITL 실행
- [ ] `scripts/locations.txt`: Seoul 좌표 추가 스니펫

---

## 완료 기준 (Definition of Done)
1. SITL 3대 실행 → 서버 시작 → GCS 화면에서 3개 드론 마커 이동 확인
2. GCS에서 drone-01 ARM 명령 → Attacker 화면에 ↑ COMMAND_LONG 패킷 표시
3. ARM ACCEPTED → GCS 로그에 초록으로 표시
4. Attacker 화면 드론 필터로 drone-02만 선택 → drone-02 패킷만 표시
