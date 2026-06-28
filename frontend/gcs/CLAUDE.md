# frontend/gcs/ — GCS(지휘소) 화면 규칙

## 역할
실제 전장의 QGroundControl(QGC) 역할.
드론 실시간 위치 지도 + 명령 전송 UI.

## 파일 구조
```
frontend/gcs/
├── index.html   # 레이아웃 + 스크립트 로드
└── main.js      # WebSocket 연결, 지도, 명령 UI 로직
```
빌드 도구 없음. CDN에서 Leaflet.js 직접 로드.

---

## index.html 레이아웃
```
┌─────────────────────────────────────────────┐
│  [드론 선택 드롭다운]  [ARM] [TAKEOFF] [LAND] [RTL]  │
│  위도: ___  경도: ___  [GOTO]               │  ← 명령 패널
├─────────────────────────────────────────────┤
│                                             │
│           Leaflet 지도                       │  ← 지도 (70% 높이)
│   drone-01 ✈  drone-02 ✈  drone-03 ✈       │
│                                             │
├─────────────────────────────────────────────┤
│  [시각] drone-01 → ARM → ACCEPTED           │  ← 명령 로그
│  [시각] drone-02 → TAKEOFF(alt=30) → ACCEPTED│    (최근 20줄)
└─────────────────────────────────────────────┘
```

---

## main.js 설계

### WebSocket 연결
```javascript
const ws = new WebSocket(`ws://${location.host}/ws/gcs`);
ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'telemetry') updateMap(msg);
    if (msg.type === 'cmd_ack')   appendLog(msg);
};
```

### 텔레메트리 수신 → 지도 업데이트
- `msg.type === "telemetry"` 수신 시 드론 마커 위치 이동
- 마커 클릭 시 팝업: drone_id, 고도, 속도, 배터리, 모드
- 드론별 색상 구분 (drone-01=파랑, 02=빨강, 03=초록)

### 명령 전송
```javascript
async function sendCmd(drone_id, cmd, params={}) {
    const resp = await fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({drone_id, cmd, params})
    });
}
```

### 명령 로그
- `msg.type === "cmd_ack"` 수신 시 로그 추가
- 형식: `[HH:MM:SS] drone-01 → ARM → ACCEPTED`
- ACCEPTED=초록, DENIED/FAILED=빨강

---

## 규칙
- jQuery, React, Vue 사용 금지 — Vanilla JS만
- Leaflet.js CDN: `https://unpkg.com/leaflet@1.9/dist/leaflet.js`
- 초기 지도 중심: 서울 (37.5665, 126.9780), zoom=13
- WebSocket 끊기면 3초 후 자동 재연결
- 명령 버튼은 드론 선택 안 했을 때 disabled 처리
