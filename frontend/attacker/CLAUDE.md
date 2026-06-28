# frontend/attacker/ — 공격자 화면 규칙

## 역할
SiK 915MHz 라디오를 SDR로 도청하는 공격자 시점을 재현.
실제로 공중에 오가는 MAVLink 바이너리 패킷을 실시간으로 표시.

## 파일 구조
```
frontend/attacker/
├── index.html   # 레이아웃 + 스크립트 로드
└── main.js      # WebSocket 연결, 패킷 렌더링, 필터 로직
```
빌드 도구 없음. Vanilla JS.

---

## index.html 레이아웃
```
┌─────────────────────────────────────────────────┐
│  [드론 필터: ALL/01/02/03]  [타입 필터: ALL/HEARTBEAT/...] │
│  [일시정지]  [초기화]  패킷 수: 1,234            │  ← 컨트롤
├─────────────────────────────────────────────────┤
│  ↓ drone-01  GLOBAL_POSITION_INT  #33           │
│  FD 1C 00 00 00 01 BE 21 00 00 A1 2F 00 ...    │  ← hex
│    lat: 37.5665  lon: 126.9780  alt: 100.0m     │  ← 파싱
│    hdg: 270.0°   spd: 5.2 m/s                   │
│  ─────────────────────────────────────────────  │
│  ↑ GCS→01  COMMAND_LONG  #76                    │
│  FD 21 00 00 00 01 BE 4C 00 00 ...             │
│    cmd: 400 (ARM_DISARM)  param1: 1.0           │
│  ─────────────────────────────────────────────  │
│  ↓ drone-01  HEARTBEAT  #0                      │
│  FD 09 00 00 00 01 BE 00 00 00 ...             │
│    type: COPTER  mode: GUIDED  armed: true       │
└─────────────────────────────────────────────────┘
```

---

## main.js 설계

### WebSocket 연결
```javascript
const ws = new WebSocket(`ws://${location.host}/ws/attacker`);
ws.onmessage = (e) => {
    const pkt = JSON.parse(e.data);
    // pkt.type === "packet"
    // pkt.direction: "up"(GCS→드론) | "down"(드론→GCS)
    // pkt.drone_id, pkt.msg_id, pkt.msg_name
    // pkt.hex: "FD1C00..."
    // pkt.fields: {lat:37.5665, lon:126.9780, ...}
    if (!isPaused) appendPacket(pkt);
};
```

### 패킷 렌더링
```javascript
function appendPacket(pkt) {
    const dir  = pkt.direction === 'up' ? '↑' : '↓';
    const who  = pkt.direction === 'up'
                 ? `GCS→${pkt.drone_id}` : pkt.drone_id;
    const hex  = pkt.hex.match(/.{1,2}/g).join(' ');  // 2자리씩 공백
    const fields = Object.entries(pkt.fields)
                         .map(([k,v]) => `${k}: ${v}`).join('  ');
    // div 삽입 후 최대 200개 패킷만 유지 (오래된 것 제거)
}
```

### 필터
- 드론 필터: `pkt.drone_id` 기준 표시/숨김
- 타입 필터: `pkt.msg_name` 기준 표시/숨김
- 필터는 **수신 차단이 아닌 DOM 표시/숨김**으로 구현

### 시각 표현
| 방향 | 색상 | 기호 |
|------|------|------|
| 드론→GCS (down) | 초록 | ↓ |
| GCS→드론 (up) | 주황 | ↑ |

---

## 규칙
- 패킷 DOM 요소는 최대 200개 유지 (성능)
- 일시정지 중에도 WebSocket은 유지, 수신만 큐에 쌓지 않음
- hex 표시: 소문자, 2자리씩 공백 구분 (`fd 1c 00 ...`)
- 알 수 없는 msg_id는 `UNKNOWN(#N)` 표시, hex는 그대로 출력
- WebSocket 끊기면 3초 후 자동 재연결
