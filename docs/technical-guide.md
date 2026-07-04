# UAV 보안 테스트베드 기술 가이드  <!-- omit in toc -->

## 목차  <!-- omit in toc -->

- [1. 시스템 개요](#1-시스템-개요)
  - [1.1. 목적](#11-목적)
  - [1.2. 전체 아키텍처](#12-전체-아키텍처)
  - [1.3. 포트 구성](#13-포트-구성)
  - [1.4. 머신 역할](#14-머신-역할)
- [2. 파일 구조](#2-파일-구조)
  - [2.1. 백엔드](#21-백엔드)
  - [2.2. 프론트엔드](#22-프론트엔드)
  - [2.3. 스크립트](#23-스크립트)
- [3. 통신 프로토콜](#3-통신-프로토콜)
  - [3.1. MAVLink v2 패킷 구조](#31-mavlink-v2-패킷-구조)
  - [3.2. MAVLink v2 서명 구조](#32-mavlink-v2-서명-구조)
  - [3.3. WebSocket 스키마](#33-websocket-스키마)
    - [3.3.1. /ws/gcs 수신 메시지](#331-wsgcs-수신-메시지)
    - [3.3.2. /ws/attacker 수신 메시지](#332-wsattacker-수신-메시지)
  - [3.4. REST API](#34-rest-api)
- [4. 핵심 구현](#4-핵심-구현)
  - [4.1. app/mavlink.py — MAVLink 인코딩·디코딩](#41-appmavlinkpy--mavlink-인코딩디코딩)
    - [4.1.1. 지원 메시지 목록](#411-지원-메시지-목록)
    - [4.1.2. 디코딩 함수](#412-디코딩-함수)
    - [4.1.3. 인코딩 함수](#413-인코딩-함수)
  - [4.2. app/sitl.py — SITL 커넥터](#42-appsitlpy--sitl-커넥터)
    - [4.2.1. 연결 흐름](#421-연결-흐름)
    - [4.2.2. 주요 메서드](#422-주요-메서드)
    - [4.2.3. EKF 준비 조건](#423-ekf-준비-조건)
  - [4.3. app/main.py — FastAPI 허브](#43-appmainpy--fastapi-허브)
    - [4.3.1. 브로드캐스트 루프](#431-브로드캐스트-루프)
    - [4.3.2. 명령 처리 흐름](#432-명령-처리-흐름)
- [5. 드론 제어 명령](#5-드론-제어-명령)
  - [5.1. 지원 명령 목록](#51-지원-명령-목록)
  - [5.2. 구현 quirk](#52-구현-quirk)
  - [5.3. ArduCopter 모드 번호](#53-ardupilot-모드-번호)
- [6. 공격 시나리오](#6-공격-시나리오)
  - [6.1. §3.2 V1 직접 주입 공격 ✅](#61-32-v1-직접-주입-공격-)
    - [6.1.1. 개요](#611-개요)
    - [6.1.2. 공격 흐름](#612-공격-흐름)
    - [6.1.3. 실행 방법](#613-실행-방법)
  - [6.2. §3.3 MAVLink v2 서명 방어 ✅](#62-33-mavlink-v2-서명-방어-)
    - [6.2.1. 개요](#621-개요)
    - [6.2.2. 방어 흐름](#622-방어-흐름)
    - [6.2.3. A/B 비교 실험 순서](#623-ab-비교-실험-순서)
  - [6.3. §3.4 GNSS 기만 공격 ❌](#63-34-gnss-기만-공격-)
    - [6.3.1. 개요](#631-개요)
    - [6.3.2. 구현 방향](#632-구현-방향)
  - [6.4. §3.4 통신 두절 공격 ❌](#64-34-통신-두절-공격-)
    - [6.4.1. 개요](#641-개요)
    - [6.4.2. 구현 방향](#642-구현-방향)
- [7. AI 에이전트 설계 (§4)](#7-ai-에이전트-설계-4)
  - [7.1. 관측 공간](#71-관측-공간)
  - [7.2. 행동 공간](#72-행동-공간)
    - [7.2.1. Red Agent (공격자)](#721-red-agent-공격자)
    - [7.2.2. Blue Agent (방어자)](#722-blue-agent-방어자)
  - [7.3. 에이전트 루프 구조](#73-에이전트-루프-구조)
  - [7.4. WebSocket 관측 클라이언트](#74-websocket-관측-클라이언트)
- [8. 개발 환경](#8-개발-환경)
  - [8.1. 환경 구성](#81-환경-구성)
  - [8.2. 서버 실행](#82-서버-실행)
  - [8.3. 코드 동기화 흐름](#83-코드-동기화-흐름)
- [9. 참조](#9-참조)

- - -

## 1. 시스템 개요

### 1.1. 목적

실제 전장 지휘소·드론 통신 구조를 재현하여 MAVLink 기반 UAV 통신에 대한 공격 시나리오를 실험하고 방어 기법을 연구한다.

세 가지 핵심 목표:
1. **실제 구조 재현**: 실제 전장 지휘소(GCS)와 드론 통신 구조를 그대로 모델링
2. **공격자 화면**: 실제로 오가는 MAVLink 바이너리 패킷을 hex + 파싱 결과로 실시간 표시
3. **GCS 화면**: 명령 전송 UI + 드론 위치 Leaflet 지도

### 1.2. 전체 아키텍처

```
실제 전장:
  [QGC] ── MAVLink binary ──→ [SiK 915MHz] ──→ [드론 FC]

본 테스트베드:
  [브라우저 GCS]      ─── WebSocket JSON ───→ [FastAPI]
  [브라우저 Attacker] ←── WebSocket JSON ──── [FastAPI] ── MAVLink v2 binary ──→ [ArduCopter SITL ×3]
                                                              ↑
                                                    R1이 지키는 구간 (바이너리 전용)
```

**계층 규칙**

| 구간 | 프로토콜 | 규칙 |
|------|---------|------|
| 브라우저 ↔ 서버 | WebSocket JSON | R3: JSON 스트림만 허용 |
| 서버 ↔ SITL | MAVLink v2 binary | R1: 바이너리만 허용, JSON/REST/문자열 금지 |

### 1.3. 포트 구성

| 역할 | 포트 | 방향 |
|------|------|------|
| FastAPI HTTP/WS | 8000 | 브라우저 → 서버 |
| SITL drone-01 (정상 통신) | 15760 | 서버 → SITL |
| SITL drone-02 (정상 통신) | 15770 | 서버 → SITL |
| SITL drone-03 (정상 통신) | 15780 | 서버 → SITL |
| SITL drone-01 (공격자 직접 접속) | 25760 | 공격 스크립트 → SITL |
| SITL drone-02 (공격자 직접 접속) | 25770 | 공격 스크립트 → SITL |
| SITL drone-03 (공격자 직접 접속) | 25780 | 공격 스크립트 → SITL |

### 1.4. 머신 역할

| 머신 | IP | 역할 |
|------|----|------|
| Windows 호스트 | 192.168.56.1 | 코드 작성, 브라우저 확인, 공격 스크립트 실행 |
| Linux VM (drone-server) | 192.168.56.101 | SITL 3대 실행, FastAPI 서버 실행 |

- - -

## 2. 파일 구조

```
uav-security-testbed/
├── app/
│   ├── main.py        ← FastAPI 앱, WebSocket 허브, 브로드캐스트 루프 (20Hz)
│   ├── mavlink.py     ← MAVLink v2 바이너리 인코딩·디코딩 (순수 함수)
│   └── sitl.py        ← SITLConnector 클래스, pymavlink TCP 수신·송신
│
├── frontend/
│   ├── gcs/
│   │   ├── index.html ← 레이아웃 (명령 패널 + Leaflet 지도 + 명령 로그)
│   │   └── main.js    ← WebSocket 연결, 드론 마커, 명령 전송
│   └── attacker/
│       ├── index.html ← 레이아웃 (필터 컨트롤 + 패킷 스트림)
│       └── main.js    ← WebSocket 연결, hex 패킷 렌더링, 드론/타입 필터
│
├── scripts/
│   ├── start_sitl.sh        ← ArduCopter SITL 3대 실행 (백그라운드)
│   ├── generate_key.py      ← 32바이트 서명 키 생성 유틸리티
│   ├── defense_signing.py   ← SITL에 MAVLink v2 서명 키 등록
│   └── inject_attack.py     ← V1 공격: SITL TCP 포트에 직접 명령 주입
│
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### 2.1. 백엔드

**`app/mavlink.py`** — 순수 함수 모듈, side-effect 없음
- `decode(raw: bytes) -> dict | None`: MAVLink v2 바이너리 → Python dict
- `encode_command(target_sysid, cmd, params) -> bytes | None`: 명령 문자열 → COMMAND_LONG 바이너리
- 모듈 레벨 `_mav_instance`: SEQ 단조증가 추적용 단일 pymavlink 인스턴스

**`app/sitl.py`** — 드론별 TCP 연결 관리
- `SITLConnector`: 드론 1대당 1개 인스턴스
- 백그라운드 스레드에서 수신 루프 실행
- `_raw_queue(maxlen=100)`: 원본 바이너리 보관
- `_ack_queue(maxlen=50)`: COMMAND_ACK 결과 보관
- `_ready` Event: HEARTBEAT 수신 + 데이터 스트림 설정 완료 시 Set

**`app/main.py`** — FastAPI 앱
- `/ws/gcs`: GCS 브라우저 연결 (텔레메트리 + ACK 수신)
- `/ws/attacker`: Attacker 브라우저 연결 (원본 패킷 스트림 수신)
- `_broadcast_loop()`: 20Hz asyncio 루프, drain_raw → decode → broadcast
- `/api/drones`: 드론 연결 상태 조회
- `/api/command`: 명령 수신 → SITL 전송 + Attacker 미러링

### 2.2. 프론트엔드

**`frontend/gcs/`** — 지휘소 화면
- Leaflet.js 지도에 드론 마커 실시간 업데이트
- ARM / DISARM / TAKEOFF / LAND / RTL / GOTO / SET_MODE 명령 전송 UI
- COMMAND_ACK 결과 로그 표시

**`frontend/attacker/`** — 공격자 화면
- 모든 MAVLink 패킷 실시간 스트리밍
- hex 덤프 + 파싱 필드 표시
- 드론별 / 메시지 타입별 필터 컨트롤

### 2.3. 스크립트

**`scripts/generate_key.py`** — 서명 키 생성 (1회성)
```
python scripts/generate_key.py --key-file signing.key
python scripts/generate_key.py --key-file signing.key --force  # 덮어쓰기
```

**`scripts/defense_signing.py`** — SITL에 서명 방어 등록
```
python scripts/defense_signing.py --drone drone-01 --key-file signing.key
python scripts/defense_signing.py --drone drone-01 --key-file signing.key --allow-unsigned
```

**`scripts/inject_attack.py`** — V1 주입 공격
```
python scripts/inject_attack.py --drone drone-01 --cmd ARM --no-sign
python scripts/inject_attack.py --drone drone-01 --cmd ARM --sign --key-file signing.key
python scripts/inject_attack.py --drone drone-01 --cmd SEQUENCE --lat 37.5 --lon 126.9 --alt 50
```

- - -

## 3. 통신 프로토콜

### 3.1. MAVLink v2 패킷 구조

MAVLink v2는 무인기(UAV)와 지상국(GCS) 간 경량 통신 프로토콜이다.  
STX `0xFD`로 시작하며 최소 12바이트(헤더 10 + CRC 2)로 구성된다.

```
 오프셋  크기  필드              설명
 ──────  ────  ────────────────  ──────────────────────────────────────
  [0]     1B   STX               패킷 시작 마커 (항상 0xFD)
  [1]     1B   LEN               페이로드 길이 (바이트)
  [2]     1B   INCOMPAT_FLAGS    호환 플래그 (0x01 = 서명 있음)
  [3]     1B   COMPAT_FLAGS      비호환 플래그 (보통 0x00)
  [4]     1B   SEQ               패킷 시퀀스 번호 (0~255 순환)
  [5]     1B   SYSID             송신 시스템 ID
  [6]     1B   COMPID            송신 컴포넌트 ID
  [7-9]   3B   MSGID             메시지 ID (3바이트, 최대 16M 종류)
  [10..] LEN   PAYLOAD           실제 데이터 (trailing zero 제거됨)
  [+2]    2B   CHECKSUM          CRC-16/MCRF4XX (CRC_EXTRA 포함)
  [+13]  13B   SIGNATURE         (선택) 서명 (INCOMPAT_FLAGS & 0x01 시 존재)
```

**v1과 v2 비교**

| 항목 | MAVLink v1 | MAVLink v2 |
|------|-----------|-----------|
| STX | 0xFE | 0xFD |
| MSGID 크기 | 1B (최대 256종) | 3B (최대 16M종) |
| 서명 | 없음 | 선택적 13B SIGNATURE |
| 하위 호환 | - | v1 패킷 수신 가능 |

### 3.2. MAVLink v2 서명 구조

서명이 활성화되면 INCOMPAT_FLAGS의 비트 0(`0x01`)이 세트되고,  
패킷 마지막에 13바이트 SIGNATURE 블록이 추가된다.

```
 SIGNATURE (13바이트)
 ──────────────────────────────────────────────────
  [0]     1B   link_id       링크 식별자
  [1-6]   6B   timestamp     단조증가 타임스탬프 (마이크로초, 40비트)
  [7-12]  6B   HMAC-SHA256   HMAC-SHA256(32바이트 키, 헤더+페이로드+CRC+link_id+timestamp)의 앞 6바이트
```

**pymavlink 서명 활성화**

```python
conn.setup_signing(
    secret_key=key,          # 32바이트 공유 키
    sign_outgoing=True,      # 송신 패킷에 서명 추가
    allow_unsigned=False,    # False → 무서명 패킷 전부 거부
)
```

`allow_unsigned=False`로 설정하면 SITL은 서명 없는 패킷을 무음으로 폐기한다.  
COMMAND_ACK가 전혀 반환되지 않으므로 공격자는 명령 수락 여부조차 알 수 없다.

### 3.3. WebSocket 스키마

#### 3.3.1. /ws/gcs 수신 메시지

**텔레메트리** (20Hz, 연결된 드론만)

```jsonc
{
  "type": "telemetry",
  "drone_id": "drone-01",
  "lat": 37.5665,
  "lon": 126.9780,
  "alt": 100.0,           // 절대고도 (m)
  "relative_alt": 50.0,   // 홈 기준 상대고도 (m)
  "vx": 2.1,              // 동쪽 속도 (m/s)
  "vy": 0.5,              // 북쪽 속도 (m/s)
  "vz": -0.2,             // 수직 속도 (m/s, 상승 = 음수)
  "groundspeed": 5.2,
  "heading": 270,
  "battery_pct": 87.0,
  "armed": true,
  "mode": "GUIDED",
  "connected": true,
  "ekf_ok": true
}
```

**명령 ACK**

```jsonc
{
  "type": "cmd_ack",
  "drone_id": "drone-01",
  "cmd": "ARM/DISARM",
  "result": "ACCEPTED"    // ACCEPTED | TEMPORARILY_REJECTED | DENIED | UNSUPPORTED | FAILED | IN_PROGRESS
}
```

#### 3.3.2. /ws/attacker 수신 메시지

```jsonc
{
  "type": "packet",
  "direction": "down",      // "down" = 드론→GCS, "up" = GCS→드론
  "drone_id": "drone-01",
  "msg_id": 33,
  "msg_name": "GLOBAL_POSITION_INT",
  "hex": "fd1c000000...",   // 소문자 hex, 공백 없음
  "fields": {               // msg_id·sysid·compid·msg_name 제외
    "lat": 37.5665,
    "lon": 126.9780,
    "alt": 100.0,
    "relative_alt": 50.0
  }
}
```

### 3.4. REST API

**GET /api/drones** — 드론 연결 상태 조회

```jsonc
{
  "drone-01": { "connected": true,  "ready": true  },
  "drone-02": { "connected": false, "ready": false },
  "drone-03": { "connected": true,  "ready": true  }
}
```

**POST /api/command** — 명령 전송

```jsonc
// 요청
{ "drone_id": "drone-01", "cmd": "ARM",     "params": {} }
{ "drone_id": "drone-01", "cmd": "DISARM",  "params": {} }
{ "drone_id": "drone-01", "cmd": "TAKEOFF", "params": { "alt": 30 } }
{ "drone_id": "drone-01", "cmd": "LAND",    "params": {} }
{ "drone_id": "drone-01", "cmd": "RTL",     "params": {} }
{ "drone_id": "drone-01", "cmd": "GOTO",    "params": { "lat": 37.5, "lon": 126.9, "alt": 30 } }
{ "drone_id": "drone-01", "cmd": "SET_MODE","params": { "mode": "GUIDED" } }

// 응답 (성공)
{ "status": "sent", "drone_id": "drone-01", "cmd": "ARM" }
```

- - -

## 4. 핵심 구현

### 4.1. app/mavlink.py — MAVLink 인코딩·디코딩

#### 4.1.1. 지원 메시지 목록

| msg_id | 메시지 이름 | 주요 파싱 필드 |
|--------|------------|--------------|
| 0 | HEARTBEAT | armed(bool), mode(str) |
| 1 | SYS_STATUS | battery_pct(float) |
| 33 | GLOBAL_POSITION_INT | lat, lon, alt, relative_alt, vx, vy, vz, hdg |
| 74 | VFR_HUD | airspeed, groundspeed, alt, climb, heading, throttle |
| 76 | COMMAND_LONG | command(int), target_system, params[7] |
| 77 | COMMAND_ACK | command(int), result(int), result_str(str) |
| 193 | EKF_STATUS_REPORT | ekf_ok(bool), flags(int) |
| 기타 | MSG_{N} | msg_name만 반환 |

#### 4.1.2. 디코딩 함수

```python
from app.mavlink import decode

raw: bytes = ...           # MAVLink v2 바이너리
parsed = decode(raw)       # dict 또는 None

# 반환 예시 (GLOBAL_POSITION_INT)
{
    "msg_id": 33,
    "sysid": 1,
    "compid": 1,
    "msg_name": "GLOBAL_POSITION_INT",
    "lat": 37.566535,
    "lon": 126.977969,
    "alt": 100.512,
    "relative_alt": 50.124,
    "vx": 2.1,
    "vy": 0.3,
    "vz": -0.1,
    "hdg": 270.0
}
```

HEARTBEAT의 `armed` 필드는 `base_mode & 0x80` 비트 마스크로 판단한다.  
`mode`는 `custom_mode` 정수를 `_COPTER_MODES` 딕셔너리로 변환한다.

#### 4.1.3. 인코딩 함수

```python
from app.mavlink import encode_command

raw = encode_command(
    target_sysid=1,
    cmd="ARM",
    params={}
)
# → MAVLink v2 COMMAND_LONG 바이너리 (bytes)
```

`encode_command`는 `_mav_instance`(모듈 레벨 단일 인스턴스)를 통해  
SEQ 번호가 자동으로 단조증가한다.

### 4.2. app/sitl.py — SITL 커넥터

#### 4.2.1. 연결 흐름

```
SITLConnector.start()
    └─ 백그라운드 스레드: _recv_loop()
            ├─ mavlink_connection("tcp:HOST:PORT", source_system=255)
            ├─ wait_heartbeat(timeout=30s)
            │       HEARTBEAT 수신 → _state["sysid"] 저장
            ├─ request_data_stream_send(10Hz)
            ├─ _ready.set()   ← is_ready() = True
            └─ recv_match 루프
                    ├─ raw → _raw_queue (maxlen=100)
                    ├─ decode() → _merge_state()
                    └─ msg_id==77 → _ack_queue (maxlen=50)
```

연결이 끊어지면 `_RECONNECT_DELAY(5초)` 후 자동 재연결한다.  
`_SITL_TIMEOUT(30초)` 동안 패킷이 없으면 재연결로 간주한다.

#### 4.2.2. 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `start()` | 수신 스레드 시작 |
| `is_ready()` | HEARTBEAT 수신 완료 여부 |
| `get_state()` | 최신 드론 상태 dict 반환 (thread-safe) |
| `drain_raw()` | 버퍼된 원본 패킷 전량 꺼내기 |
| `drain_acks()` | 버퍼된 COMMAND_ACK 전량 꺼내기 |
| `send_command(raw)` | COMMAND_LONG 바이너리 전송 |
| `send_goto(lat, lon, alt)` | SET_POSITION_TARGET_GLOBAL_INT 전송 |
| `send_set_mode(mode_id)` | set_mode_send() 전송 |

#### 4.2.3. EKF 준비 조건

GUIDED 모드로 비행하려면 EKF 상태가 준비되어야 한다.  
`EKF_STATUS_REPORT(msg_id=193)`의 flags 필드를 다음 조건으로 평가한다.

```python
ekf_ok = bool(
    (flags & 0x07) == 0x07 and   # EKF_ATTITUDE(0x01) | EKF_VELOCITY_HORIZ(0x02) | EKF_VELOCITY_VERT(0x04)
    (flags & 0x18) and            # EKF_POS_HORIZ_REL(0x08) 또는 EKF_POS_HORIZ_ABS(0x10)
    not (flags & 0x80)            # NOT EKF_CONST_POS_MODE (GPS 유실 시 켜짐 → GUIDED 불가)
)
```

`0x80(CONST_POS_MODE)`이 켜지면 GPS 신호가 없는 것이므로 GUIDED 비행이 불가하다.  
이는 GNSS 기만 공격의 탐지 지표로 활용할 수 있다.

### 4.3. app/main.py — FastAPI 허브

#### 4.3.1. 브로드캐스트 루프

```
20Hz 루프 (asyncio.sleep(0.05))
  ├─ 드론별 drain_raw() → decode() → att_mgr.broadcast(packet)
  ├─ 드론별 drain_acks() → gcs_mgr.broadcast(cmd_ack)
  └─ is_ready() 드론만 get_state() → gcs_mgr.broadcast(telemetry)
```

Attacker 브라우저는 모든 드론의 모든 패킷을 수신한다.  
GCS 브라우저는 텔레메트리와 ACK만 수신한다.

#### 4.3.2. 명령 처리 흐름

```
POST /api/command
  ├─ DRONES.get(drone_id) → SITLConnector 조회
  ├─ is_ready() 확인 (False → 503)
  ├─ SET_MODE → send_set_mode(mode_id)     [set_mode_send() 네이티브]
  ├─ GOTO    → send_goto(lat, lon, alt)    [SET_POSITION_TARGET_GLOBAL_INT]
  └─ 기타    → encode_command() → send_command(raw)
                └─ Attacker WS에 direction="up" 으로 미러링
```

- - -

## 5. 드론 제어 명령

### 5.1. 지원 명령 목록

| cmd | MAVLink 명령 | 주요 파라미터 | 설명 |
|-----|-------------|-------------|------|
| `ARM` | COMMAND_LONG(400) | p1=1.0, p2=21196 | 모터 시동 (force arm) |
| `DISARM` | COMMAND_LONG(400) | p1=0.0, p2=21196 | 모터 정지 (force disarm) |
| `TAKEOFF` | COMMAND_LONG(22) | p7=alt | 이륙 (GUIDED 모드 필요) |
| `LAND` | set_mode_send | custom_mode=9 | 착륙 모드 전환 |
| `RTL` | set_mode_send | custom_mode=6 | 홈 복귀 모드 전환 |
| `GOTO` | SET_POSITION_TARGET_GLOBAL_INT | lat, lon, alt | 좌표 이동 (GUIDED 모드) |
| `SET_MODE` | set_mode_send | mode_id | 비행 모드 전환 |

### 5.2. 구현 quirk

**GOTO 구현**  
`MAV_CMD_DO_REPOSITION(192)`는 일부 ArduCopter 버전에서 UNSUPPORTED를 반환한다.  
QGC와 동일하게 `SET_POSITION_TARGET_GLOBAL_INT`를 직접 전송한다.  
type_mask로 속도·가속도·yaw 필드를 전부 무시한다.

**ARM/DISARM**  
`p2=21196.0` (force arm/disarm)으로 SITL pre-arm 체크를 우회한다.  
실제 하드웨어에서는 이 값을 제거해야 한다.

**SET_MODE**  
`COMMAND_LONG(176)`으로 보내면 일부 버전에서 무시된다.  
반드시 pymavlink 네이티브 `set_mode_send(target_system, 1, mode_id)`를 사용한다.

### 5.3. ArduPilot 모드 번호

| 번호 | 이름 | 설명 |
|------|------|------|
| 0 | STABILIZE | 수동 자세 제어 |
| 3 | AUTO | 미션 자동 수행 |
| 4 | GUIDED | GCS 좌표 추적 (명령 실험용) |
| 5 | LOITER | 현재 위치 유지 |
| 6 | RTL | 홈 자동 복귀 |
| 9 | LAND | 수직 착륙 |

- - -

## 6. 공격 시나리오

### 6.1. §3.2 V1 직접 주입 공격 ✅

#### 6.1.1. 개요

FastAPI 서버를 완전히 우회하여 SITL TCP 포트에 직접 접속하고 MAVLink 명령을 주입한다.  
공격자가 드론 통신 포트 번호를 알고 있고 네트워크 접근이 가능할 때 유효하다.

```
공격 경로:
  [Windows 공격자] ── MAVLink binary ──→ [SITL TCP:25760] (FastAPI 우회)
  [FastAPI 서버]   ── MAVLink binary ──→ [SITL TCP:15760] (정상 통신)
```

두 연결이 같은 SITL 인스턴스를 공유하므로, 공격자의 명령이 드론에 직접 실행된다.

#### 6.1.2. 공격 흐름

```
1. mavlink_connection("tcp:192.168.56.101:25760", source_system=255)
2. wait_heartbeat() → target_system 획득
3. set_mode_send(target_system, 1, 4)   → GUIDED 모드
4. command_long_send(ARM)               → 모터 시동
5. command_long_send(TAKEOFF, alt=30)   → 이륙
6. set_position_target_global_int_send  → 목표 좌표로 이동
```

#### 6.1.3. 실행 방법

```bash
# 단일 명령 (무서명)
python scripts/inject_attack.py --drone drone-01 --cmd ARM

# 전체 시퀀스 (GUIDED → ARM → TAKEOFF → GOTO)
python scripts/inject_attack.py \
    --drone drone-01 \
    --cmd SEQUENCE \
    --lat 37.5665 --lon 126.9780 --alt 50

# 서명 키 탈취 시나리오 (서명 방어 우회)
python scripts/inject_attack.py \
    --drone drone-01 \
    --cmd ARM \
    --sign --key-file signing.key
```

---

### 6.2. §3.3 MAVLink v2 서명 방어 ✅

#### 6.2.1. 개요

MAVLink v2 서명 기능을 활용해 32바이트 공유 키를 갖지 않은 주입 공격을 차단한다.  
`setup_signing(allow_unsigned=False)` 호출 후 SITL은 무서명 패킷을 무음으로 폐기한다.

#### 6.2.2. 방어 흐름

```
1. generate_key.py → signing.key (32바이트 랜덤 키)
2. defense_signing.py
   ├─ connect(drone-01) as source_system=254
   ├─ setup_signing(key, allow_unsigned=False)
   └─ verify: 서명된 ARM 전송 → ACCEPTED 확인
              무서명 ARM 전송 → ACK 없음 확인
```

```
서명 방어 후 공격 시나리오:
  [공격자, 키 없음]  → 무서명 ARM  → SITL 폐기 (ACK 없음)  ← 방어 성공
  [공격자, 키 탈취]  → 서명된 ARM  → SITL 수락 (ACCEPTED)  ← 키 관리 필요
```

#### 6.2.3. A/B 비교 실험 순서

```bash
# Step 1: 키 생성
python scripts/generate_key.py --key-file signing.key

# Step 2: 방어 등록
python scripts/defense_signing.py --drone drone-01 --key-file signing.key

# Step 3: 무서명 공격 → 묵살 확인
python scripts/inject_attack.py --drone drone-01 --cmd ARM --no-sign
# 출력: [ACK] 타임아웃 (방어 성공)

# Step 4: 서명 공격 → 수락 확인 (키 탈취 시나리오)
python scripts/inject_attack.py --drone drone-01 --cmd ARM --sign --key-file signing.key
# 출력: [ACK] cmd=400 → ACCEPTED
```

---

### 6.3. §3.4 GNSS 기만 공격 ❌

#### 6.3.1. 개요

드론에 가짜 GPS 좌표(GPS_INPUT, msg_id=113)를 주입하여 실제 위치와 다른 위치를 보고하게 만든다.  
GCS 화면에는 드론이 정상 위치에 있는 것처럼 표시되지만 실제 드론은 다른 곳에 있다.

```
공격 효과:
  드론 실제 위치: 37.5665, 126.9780
  GCS 표시 위치: 37.6000, 127.0000 (기만된 값)
  GCS 지도: 드론이 5km 벗어난 위치에 있는 것처럼 표시
```

#### 6.3.2. 구현 방향

```python
# scripts/attack_gnss_spoof.py (미구현)
# GPS_INPUT (msg_id=113) 으로 위치를 점진적으로 오프셋
conn.mav.gps_input_send(
    time_usec=int(time.time() * 1e6),
    gps_id=0,
    ignore_flags=0,
    time_week_ms=...,
    time_week=...,
    fix_type=3,           # 3D fix
    lat=int((real_lat + offset_lat) * 1e7),
    lon=int((real_lon + offset_lon) * 1e7),
    alt=real_alt,
    hdop=0.5,
    vdop=0.5,
    vn=0.0, ve=0.0, vd=0.0,
    speed_accuracy=0.2,
    horiz_accuracy=0.5,
    vert_accuracy=0.5,
    satellites_visible=8,
)
```

탐지 신호: EKF flags `0x80(CONST_POS_MODE)` 켜짐, 위치 점프, groundspeed 이상값

---

### 6.4. §3.4 통신 두절 공격 ❌

#### 6.4.1. 개요

GCS의 HEARTBEAT 송신을 중단하여 드론이 Failsafe를 발동하게 만든다.  
ArduCopter는 GCS HEARTBEAT가 일정 시간(기본 5초) 없으면 자동으로 RTL 또는 LAND로 전환한다.

```
공격 효과:
  1. GCS HEARTBEAT 차단 (iptables 또는 FastAPI 중단)
  2. 드론: Failsafe 발동 → RTL 모드 전환
  3. 복귀 경로 + 착륙 타이밍이 예측 가능해져 물리적 위협 가능
```

#### 6.4.2. 구현 방향

```python
# scripts/attack_blackout.py (미구현)
# 방법 1: FastAPI 브로드캐스트 루프에서 HEARTBEAT 전송 중단
# 방법 2: 네트워크 레벨에서 포트 차단 (iptables -A INPUT -p tcp --dport 15760 -j DROP)
# 방법 3: SITL TCP 연결 강제 종료 후 Failsafe 관찰

# Failsafe 타이밍 측정
# → HEARTBEAT 중단 후 RTL 전환까지 N초, 착륙까지 N초
# → 이 구간에서 재주입 공격 시 효과 측정
```

탐지 신호: HEARTBEAT 수신 빈도 저하, mode → RTL/LAND 비정상 전환, groundspeed 급변

- - -

## 7. AI 에이전트 설계 (§4)

### 7.1. 관측 공간

AI 에이전트는 `/ws/attacker` WebSocket을 통해 아래 정보를 실시간으로 관측한다.

| 관측 필드 | 출처 메시지 | 에이전트 활용 |
|----------|------------|-------------|
| `lat`, `lon`, `alt` | GLOBAL_POSITION_INT | 위치 이상 탐지, 이동 경로 분석 |
| `relative_alt` | GLOBAL_POSITION_INT | 이륙/착륙 단계 판단 |
| `vx`, `vy`, `vz` | GLOBAL_POSITION_INT | 속도 이상 탐지 |
| `armed` | HEARTBEAT | 모터 상태 변화 감지 |
| `mode` | HEARTBEAT | 모드 전환 이상 탐지 |
| `battery_pct` | SYS_STATUS | 배터리 기반 상황 판단 |
| `groundspeed` | VFR_HUD | 비행 중 속도 이상 감지 |
| `ekf_ok`, `flags` | EKF_STATUS_REPORT | GPS 유실 / GNSS 기만 탐지 |
| `direction`, `msg_name` | 패킷 메타 | 명령 발생 방향 구분 (down/up) |
| `hex` | 패킷 원본 | 서명 유무 분석, 이상 패킷 탐지 |

### 7.2. 행동 공간

#### 7.2.1. Red Agent (공격자)

| 행동 | 구현 함수 | 설명 |
|------|----------|------|
| `inject_arm` | `send_cmd(conn, "ARM", {})` | 무단 ARM |
| `inject_disarm` | `send_cmd(conn, "DISARM", {})` | 비행 중 강제 DISARM |
| `inject_goto` | `send_cmd(conn, "GOTO", {lat, lon, alt})` | 좌표 탈취 |
| `inject_land` | `send_cmd(conn, "LAND", {})` | 강제 착륙 |
| `inject_rtl` | `send_cmd(conn, "RTL", {})` | 홈 복귀 강제 |
| `gnss_spoof` | GPS_INPUT 주입 | 위치 기만 |
| `blackout` | HEARTBEAT 차단 | Failsafe 유도 |

#### 7.2.2. Blue Agent (방어자)

| 행동 | API 호출 | 설명 |
|------|---------|------|
| `arm_drone` | POST /api/command ARM | 정상 ARM |
| `disarm_drone` | POST /api/command DISARM | 안전 정지 |
| `set_mode_loiter` | POST /api/command SET_MODE LOITER | 현 위치 유지 |
| `emergency_land` | POST /api/command LAND | 긴급 착륙 |
| `enable_signing` | defense_signing.py | 서명 방어 활성화 |
| `alert` | 로그/알림 | 이상 탐지 경보 |

### 7.3. 에이전트 루프 구조

```
while True:
    1. Observe
       └─ ws.recv() → JSON 파싱 → 상태 벡터 구성
          [lat, lon, alt, armed, mode, ekf_ok, groundspeed, ...]

    2. Decide
       ├─ Rule-based: if mode == "RTL" and not commanded → alert
       └─ LLM (claude-opus-4-8):
          system_prompt = "당신은 UAV 보안 AI입니다..."
          user_msg = f"현재 상태: {state}\n최근 패킷: {recent_packets}"
          → 행동 선택 (JSON tool call)

    3. Act
       └─ 선택된 행동 실행 (POST /api/command 또는 직접 MAVLink 주입)

    4. Verify
       └─ 다음 텔레메트리에서 행동 결과 확인
          (armed 상태 변경, mode 전환, ACK 수신 여부)
```

### 7.4. WebSocket 관측 클라이언트

```python
import asyncio
import json
import websockets

async def observe(on_packet):
    async with websockets.connect("ws://192.168.56.101:8000/ws/attacker") as ws:
        async for raw in ws:
            pkt = json.loads(raw)
            if pkt["type"] == "packet":
                await on_packet(pkt)

async def agent_loop():
    state = {}
    async def handle(pkt):
        # 텔레메트리 필드 누적
        state.update(pkt.get("fields", {}))
        state["direction"]  = pkt["direction"]
        state["msg_name"]   = pkt["msg_name"]
        state["drone_id"]   = pkt["drone_id"]
        # 이상 탐지 예시
        if pkt["msg_name"] == "HEARTBEAT":
            mode = pkt["fields"].get("mode", "")
            if mode == "RTL" and not state.get("rtl_commanded"):
                print(f"[ALERT] 비정상 RTL 전환 감지: drone={pkt['drone_id']}")
    await observe(handle)

asyncio.run(agent_loop())
```

- - -

## 8. 개발 환경

### 8.1. 환경 구성

| 항목 | 값 |
|------|---|
| 백엔드 | Python 3.11 + FastAPI + pymavlink |
| 프론트엔드 | Vanilla JS + Leaflet.js (빌드 도구 없음) |
| SITL | ArduPilot ArduCopter (실제 FC 펌웨어) |
| 가상화 | VirtualBox + 공유폴더 자동 동기화 |
| 의존성 | `requirements.txt` |

```
# requirements.txt
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pymavlink>=2.4.41
aiofiles>=23.0.0
```

### 8.2. 서버 실행

```bash
# VM에서 (매 세션)
source ~/venv-ardupilot/bin/activate
cd /media/sf_uav

# SITL 3대 실행
bash scripts/start_sitl.sh

# FastAPI 서버 실행 (코드 변경 시 자동 재시작)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**접속 URL** (Windows 브라우저에서)

| 화면 | URL |
|------|-----|
| GCS | http://192.168.56.101:8000/gcs/ |
| Attacker | http://192.168.56.101:8000/attacker/ |
| 드론 상태 API | http://192.168.56.101:8000/api/drones |

### 8.3. 코드 동기화 흐름

```
Windows에서 코드 수정·저장
    ↓ VirtualBox 공유폴더 (자동 동기화, 별도 전송 없음)
VM /media/sf_uav/ 에 즉시 반영
    ↓ uvicorn --reload 가 변경 감지 후 자동 재시작
Windows 브라우저에서 확인
```

- - -

## 9. 참조

**구현 완료**

| 단계 | 파일 | 상태 |
|------|------|------|
| Phase 1: MAVLink 인코딩·디코딩 | app/mavlink.py | ✅ 완료 |
| Phase 2: SITL TCP 수신·송신 | app/sitl.py | ✅ 완료 |
| Phase 3: FastAPI WebSocket 허브 | app/main.py | ✅ 완료 |
| Phase 4: GCS 프론트엔드 | frontend/gcs/ | ✅ 완료 |
| Phase 5: Attacker 프론트엔드 | frontend/attacker/ | ✅ 완료 |
| §3.2: V1 직접 주입 공격 | scripts/inject_attack.py | ✅ 완료 |
| §3.3: MAVLink v2 서명 방어 | scripts/defense_signing.py | ✅ 완료 |

**미구현 (다음 단계)**

| 단계 | 파일 | 상태 |
|------|------|------|
| §3.4: GNSS 기만 공격 | scripts/attack_gnss_spoof.py | ❌ 미구현 |
| §3.4: 통신 두절 공격 | scripts/attack_blackout.py | ❌ 미구현 |
| §4: Red AI 에이전트 | scripts/agent_red.py | ❌ 미구현 |
| §4: Blue AI 에이전트 | scripts/agent_blue.py | ❌ 미구현 |

**관련 자료**
- [MAVLink v2 프로토콜 공식 문서](https://mavlink.io/en/guide/mavlink_2.html)
- [pymavlink GitHub](https://github.com/ArduPilot/pymavlink)
- [ArduPilot SITL 문서](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html)
- [BOB4Drone Drone Hacking Guideline](https://github.com/BOB4Drone/Drone_Hacking_Guideline)
