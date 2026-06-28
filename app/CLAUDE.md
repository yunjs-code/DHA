# app/ — 백엔드 구현 규칙

## 파일 역할
| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱, WebSocket 허브, 브로드캐스트 루프 |
| `sitl.py` | pymavlink UDP 수신·파싱, SITL 상태 캐시 |
| `mavlink.py` | MAVLink v2 바이너리 인코딩·디코딩 (순수 함수) |

---

## main.py 설계

### WebSocket 엔드포인트
- `GET /ws/gcs` → GCS 클라이언트 연결 (브라우저 지도·명령 UI)
- `GET /ws/attacker` → 공격자 클라이언트 연결 (패킷 스트림)

### 브로드캐스트 루프 (백그라운드 태스크)
```
while True:
    for connector in sitl_connectors:
        raw_bytes = connector.recv_raw()   # 원본 바이너리
        parsed    = mavlink.decode(raw_bytes)
        gcs_msg   = {"type":"telemetry", "drone_id":..., "lat":..., ...}
        attacker_msg = {"type":"packet", "direction":"down",
                        "drone_id":..., "msg_id":...,
                        "hex": raw_bytes.hex(), "fields": parsed}
        broadcast(gcs_clients, gcs_msg)
        broadcast(attacker_clients, attacker_msg)
    await asyncio.sleep(0.05)   # 20 Hz
```

### REST 엔드포인트 (최소)
- `GET /api/drones` → 연결된 드론 목록
- `POST /api/command` → GCS 명령 수신 → mavlink.encode → UDP → SITL
  - body: `{"drone_id":"drone-01","cmd":"ARM","params":{}}`
  - 명령 전송 후 attacker WebSocket에도 미러링 (direction: "up")

---

## sitl.py 설계

### SITLConnector 클래스
```python
class SITLConnector:
    def __init__(self, drone_id: str, udp_port: int): ...
    def start(self) -> None:       # 백그라운드 스레드 시작
    def recv_raw(self) -> bytes | None:  # 최신 수신 바이너리 반환
    def get_state(self) -> dict:   # 파싱된 최신 상태 반환
    def send_command(self, raw: bytes) -> None:  # UDP로 전송
```

### 수신 스레드
- `pymavlink.mavutil.mavlink_connection('udpin:0.0.0.0:PORT')`
- 수신 메시지 타입: HEARTBEAT, GLOBAL_POSITION_INT, SYS_STATUS, VFR_HUD
- 원본 바이너리와 파싱 상태를 둘 다 캐시 (raw_bytes, state dict)

### 규칙
- recv_raw()는 원본 바이너리를 **가공 없이** 반환
- JSON 변환은 main.py에서만 수행
- 스레드는 daemon=True, 크래시해도 메인 루프에 영향 없음

---

## mavlink.py 설계

### 디코딩 (binary → dict)
```python
def decode(raw: bytes) -> dict | None:
    # STX=0xFD 확인, msg_id 추출, 주요 필드 파싱
    # 지원: HEARTBEAT(0), SYS_STATUS(1),
    #        GLOBAL_POSITION_INT(33), VFR_HUD(74),
    #        COMMAND_LONG(76), COMMAND_ACK(77)
    # 미지원 msg_id는 {"msg_id": N, "raw": hex} 반환
```

### 인코딩 (dict → binary)
```python
def encode_command(drone_id: str, cmd: str, params: dict) -> bytes:
    # cmd: "ARM" | "DISARM" | "TAKEOFF" | "LAND" | "RTL" | "GOTO"
    # COMMAND_LONG 바이너리 생성
    # pymavlink의 mav.command_long_encode() 활용
```

### 규칙
- 이 파일의 함수는 순수 함수 (side-effect 없음)
- 파싱 실패는 예외 대신 None 반환
- struct 언패킹은 공식 MAVLink v2 레이아웃 기준

---

## 공통 규칙
- 비동기: asyncio (FastAPI 기본), 블로킹 IO는 스레드풀
- 로그: `logging.getLogger(__name__)`, print() 사용 금지
- 타입 힌트 필수, Any 타입 최소화
