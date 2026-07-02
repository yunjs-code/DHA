# UAV Security Testbed — 프로젝트 규칙

## 목표 (3가지만)
1. 실제 전장 지휘소·드론 통신 구조를 그대로 재현
2. 공격자 화면: 실제로 오가는 MAVLink 바이너리 패킷 표시
3. GCS 화면: 명령 전송 UI + 드론 위치 지도

## ★ 절대 규칙 — 어떤 이유로도 어기지 않는다

### R1. 서버 ↔ SITL 구간은 MAVLink v2 바이너리만 허용
- JSON 직렬화, REST 호출, 문자열 명령 전달 금지
- pymavlink recv → 파싱 → WebSocket JSON 순서만 허용
- SITL로 보내는 명령: 반드시 COMMAND_LONG 바이너리로 인코딩

### R2. 금지 기능 목록 — 추가하지 않는다
- AI/ML 탐지 (IsolationForest, RuleEngine 등)
- 공격 주입 시뮬레이터 (AttackManager, injector)
- MQTT 브로커 연동
- SATCOM/위성 채널 에뮬레이션
- RTSP 영상 스트림
- 시나리오 엔진
- 시뮬레이션 전용 내부 필드 (`_ground_truth`, `malformed`)

### R3. 브라우저 ↔ 서버는 WebSocket JSON만 허용
- GCS: 드론 위치·상태를 JSON으로 수신, 명령을 JSON으로 송신
- Attacker: MAVLink 패킷을 hex + 파싱 결과 JSON으로 수신
- REST API는 서버 상태 조회용 최소한만 허용

## 실제 전장 vs 우리 구조
```
실제: [QGC] ── MAVLink binary ──→ [SiK 915MHz] ──→ [드론 FC]
우리: [브라우저] ── WS JSON ──→ [서버] ── MAVLink binary ──→ [SITL]
                                          ↑ R1이 지키는 구간
```

## 파일 구조
```
app/
├── main.py        ← FastAPI 앱, WebSocket 허브, 브로드캐스트 루프 (20Hz)
├── mavlink.py     ← MAVLink v2 바이너리 인코딩·디코딩 (순수 함수)
└── sitl.py        ← SITLConnector 클래스, pymavlink TCP 수신·송신

frontend/
├── gcs/
│   ├── index.html ← 레이아웃 (명령 패널 + Leaflet 지도 + 명령 로그)
│   └── main.js    ← WebSocket 연결, 드론 마커, 명령 전송 fetch
└── attacker/
    ├── index.html ← 레이아웃 (필터 컨트롤 + 패킷 스트림)
    └── main.js    ← WebSocket 연결, hex 패킷 렌더링, 드론/타입 필터

scripts/
└── start_sitl.sh  ← ArduCopter SITL 3대 실행 (백그라운드)
```

## 포트
| 용도 | 포트 | 프로토콜 |
|------|------|---------|
| FastAPI HTTP/WS | 8000 | TCP |
| SITL drone-01 | 5760 | TCP (서버가 접속) |
| SITL drone-02 | 5770 | TCP (서버가 접속) |
| SITL drone-03 | 5780 | TCP (서버가 접속) |

## 스택
- 백엔드: Python 3.11 + FastAPI + pymavlink
- 프론트엔드: Vanilla JS + Leaflet.js (빌드 도구 없음)
- SITL: ArduPilot ArduCopter (실제 FC 펌웨어)
- 의존성: `requirements.txt` 기준, 새 패키지 추가 시 반드시 기재

---

## 현재 구현 상태 (소스 탐색 없이 참조용)

### WebSocket 메시지 스키마

#### /ws/gcs 수신 (서버 → GCS 브라우저)
```jsonc
// 텔레메트리 (20Hz, 연결된 드론만)
{
  "type": "telemetry",
  "drone_id": "drone-01",
  "lat": 37.5665, "lon": 126.9780,
  "alt": 100.0,           // 절대고도 (m)
  "relative_alt": 50.0,   // 홈 기준 상대고도 (m)
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
  "cmd": "ARM/DISARM",       // 사람이 읽을 수 있는 명령 이름
  "result": "ACCEPTED"       // ACCEPTED | TEMPORARILY_REJECTED | DENIED | UNSUPPORTED | FAILED | IN_PROGRESS
}
```

#### /ws/attacker 수신 (서버 → Attacker 브라우저)
```jsonc
// 모든 MAVLink 패킷 (down=드론→GCS, up=GCS→드론)
{
  "type": "packet",
  "direction": "down",       // "down" | "up"
  "drone_id": "drone-01",
  "msg_id": 33,
  "msg_name": "GLOBAL_POSITION_INT",
  "hex": "fd1c000000...",    // 소문자 hex, 공백 없음
  "fields": {                // msg_id·sysid·compid·msg_name 제외한 파싱 필드
    "lat": 37.5665,
    "lon": 126.9780,
    "alt": 100.0,
    "relative_alt": 50.0
  }
}
```

### REST API

#### GET /api/drones
```jsonc
{
  "drone-01": { "connected": true,  "ready": true  },
  "drone-02": { "connected": false, "ready": false },
  "drone-03": { "connected": true,  "ready": true  }
}
```

#### POST /api/command
```jsonc
// 요청
{ "drone_id": "drone-01", "cmd": "ARM",    "params": {} }
{ "drone_id": "drone-01", "cmd": "DISARM", "params": {} }
{ "drone_id": "drone-01", "cmd": "TAKEOFF","params": { "alt": 30 } }
{ "drone_id": "drone-01", "cmd": "LAND",   "params": {} }
{ "drone_id": "drone-01", "cmd": "RTL",    "params": {} }
{ "drone_id": "drone-01", "cmd": "GOTO",   "params": { "lat": 37.5, "lon": 126.9, "alt": 30 } }
{ "drone_id": "drone-01", "cmd": "SET_MODE","params": { "mode": "GUIDED" } }

// 응답 (성공)
{ "status": "sent", "drone_id": "drone-01", "cmd": "ARM" }
```

### mavlink.py — 디코딩 지원 msg_id
| msg_id | 이름 | 주요 필드 |
|--------|------|-----------|
| 0 | HEARTBEAT | armed, mode |
| 1 | SYS_STATUS | battery_pct |
| 33 | GLOBAL_POSITION_INT | lat, lon, alt, relative_alt, vx, vy, vz, hdg |
| 74 | VFR_HUD | airspeed, groundspeed, alt, climb, heading, throttle |
| 76 | COMMAND_LONG | command, target_system, params[7] |
| 77 | COMMAND_ACK | command, result, result_str |
| 193 | EKF_STATUS_REPORT | ekf_ok, flags |
| 기타 | MSG_N | msg_name만 반환 |

### 주요 구현 quirk (읽어두면 디버깅 시간 절약)

- **GOTO**: `MAV_CMD_DO_REPOSITION(192)`는 일부 ArduCopter 버전에서 UNSUPPORTED 반환.
  대신 `SET_POSITION_TARGET_GLOBAL_INT`를 직접 전송 (`send_goto()`).
  QGC와 동일한 방식.

- **ARM/DISARM**: `p2=21196.0` (force arm/disarm) — SITL pre-arm 체크 우회.
  실제 하드웨어에서는 제거 필요.

- **SET_MODE**: `command_long_encode`가 아닌 `set_mode_send()` 네이티브 사용.
  COMMAND_LONG(176)로 보내면 일부 버전에서 무시됨.

- **포트**: drone-02는 5770, drone-03는 5780 (10 단위 증가, 1 단위 아님).

- **SITLConnector**: TCP 직접 접속 (MAVProxy 불필요). `_ready` Event가 Set되면
  HEARTBEAT 수신 완료 → 데이터 스트림 10Hz 요청 완료 상태.

- **브로드캐스트**: 명령 전송 후 Attacker WS에도 미러링 (direction="up").
  패킷 큐 maxlen=100, 20Hz 루프에서 drain_raw()로 전부 꺼냄.

- **EKF 준비 조건**: `(flags & 0x07)==0x07` AND `(flags & 0x18)!=0` AND `NOT (flags & 0x80)`.
  GPS 유실 시 0x80(CONST_POS_MODE) 켜짐 → ekf_ok=False → GUIDED 비행 불가.

### 드론 모드 번호 매핑 (ArduCopter)
| 번호 | 이름 |
|------|------|
| 0 | STABILIZE |
| 3 | AUTO |
| 4 | GUIDED |
| 5 | LOITER |
| 6 | RTL |
| 9 | LAND |

---

## 개발 환경

### 머신 역할
| 머신 | IP | 하는 일 |
|------|----|---------|
| Windows 호스트 | 192.168.56.1 | 코드 작성 (Claude/VS Code), 브라우저로 화면 확인 |
| Linux VM (drone-server) | 192.168.56.101 | SITL 실행, FastAPI 서버 실행 |

### 코드 흐름
```
Windows에서 코드 작성·저장
    ↓ VirtualBox 공유폴더 (자동 동기화, 별도 전송 없음)
VM /media/sf_uav/ 에 즉시 반영
    ↓ uvicorn --reload 가 변경 감지 후 자동 재시작
Windows 브라우저에서 http://192.168.56.101:8000 접속해서 확인
```

### VM 서버 실행 명령 (매 세션)
```bash
source ~/venv-ardupilot/bin/activate
cd /media/sf_uav
bash scripts/start_sitl.sh          # SITL 3대 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 구현 완료 단계
```
Phase 1: app/mavlink.py   ✅ MAVLink v2 바이너리 인코딩·디코딩
Phase 2: app/sitl.py      ✅ pymavlink TCP 수신·송신 (SITLConnector)
Phase 3: app/main.py      ✅ FastAPI WebSocket 허브 + 브로드캐스트
Phase 4: frontend/gcs/    ✅ 지도 + 명령 UI
Phase 5: frontend/attacker/ ✅ 패킷 스트림 뷰어
```
