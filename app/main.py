"""FastAPI WebSocket 허브 — GCS·Attacker 브라우저와 SITL 연결."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import mavlink as mav
from app.sitl import SITLConnector

log = logging.getLogger(__name__)

# ── SITL 커넥터 (서버 시작 시 TCP 접속) ──────────────────────────────────────

DRONES: dict[str, SITLConnector] = {
    "drone-01": SITLConnector("drone-01", 14560),
    "drone-02": SITLConnector("drone-02", 14570),
    "drone-03": SITLConnector("drone-03", 14580),
}

# ── WebSocket 연결 관리 ────────────────────────────────────────────────────────

class _WsManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        log.info("WS 연결: %s (총 %d)", ws.client, len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.remove(ws)
        log.info("WS 해제: %s (총 %d)", ws.client, len(self._clients))

    async def broadcast(self, data: dict) -> None:
        if not self._clients:
            return
        text = json.dumps(data, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.remove(ws)


gcs_mgr  = _WsManager()
att_mgr  = _WsManager()

# ── 브로드캐스트 루프 (20Hz) ──────────────────────────────────────────────────

async def _broadcast_loop() -> None:
    while True:
        await asyncio.sleep(0.05)  # 20 Hz

        for drone_id, connector in DRONES.items():

            # Attacker: 버퍼된 모든 원본 패킷 전송
            for raw in connector.drain_raw():
                parsed = mav.decode(raw)
                if parsed is None:
                    continue
                await att_mgr.broadcast({
                    "type":      "packet",
                    "direction": "down",
                    "drone_id":  drone_id,
                    "msg_id":    parsed.get("msg_id", -1),
                    "msg_name":  parsed.get("msg_name", "UNKNOWN"),
                    "hex":       raw.hex(),
                    "fields":    _strip_meta(parsed),
                })

            # GCS: 최신 상태 텔레메트리 (연결된 드론만)
            if not connector.is_ready():
                continue
            s = connector.get_state()
            await gcs_mgr.broadcast({
                "type":         "telemetry",
                "drone_id":     drone_id,
                "lat":          s.get("lat", 0.0),
                "lon":          s.get("lon", 0.0),
                "alt":          s.get("alt", 0.0),
                "relative_alt": s.get("relative_alt", 0.0),
                "groundspeed":  s.get("groundspeed", 0.0),
                "heading":      s.get("heading", s.get("hdg", 0)),
                "battery_pct":  s.get("battery_pct", 100.0),
                "armed":        s.get("armed", False),
                "mode":         s.get("mode", ""),
                "connected":    s.get("connected", False),
            })


def _strip_meta(parsed: dict) -> dict:
    return {k: v for k, v in parsed.items()
            if k not in ("msg_id", "sysid", "compid", "msg_name")}


# ── FastAPI 앱 ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    for connector in DRONES.values():
        connector.start()
    task = asyncio.create_task(_broadcast_loop())
    log.info("SITL 커넥터 %d대 시작, 브로드캐스트 루프 가동", len(DRONES))
    yield
    task.cancel()


app = FastAPI(title="UAV Security Testbed", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/gcs")
async def ws_gcs(ws: WebSocket):
    await gcs_mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()  # 연결 유지 (클라이언트 ping)
    except WebSocketDisconnect:
        gcs_mgr.disconnect(ws)


@app.websocket("/ws/attacker")
async def ws_attacker(ws: WebSocket):
    await att_mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        att_mgr.disconnect(ws)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/drones")
async def api_drones():
    return JSONResponse({
        drone_id: {
            "connected": c.get_state().get("connected", False),
            "ready":     c.is_ready(),
        }
        for drone_id, c in DRONES.items()
    })


class CommandRequest(BaseModel):
    drone_id: str
    cmd: str
    params: dict = {}


@app.post("/api/command")
async def api_command(req: CommandRequest):
    connector = DRONES.get(req.drone_id)
    if connector is None:
        return JSONResponse({"error": f"알 수 없는 드론: {req.drone_id}"}, status_code=404)
    if not connector.is_ready():
        return JSONResponse({"error": "SITL 미연결"}, status_code=503)

    # SET_MODE는 네이티브 set_mode_send 사용 (COMMAND_LONG보다 신뢰성 높음)
    if req.cmd == "SET_MODE":
        _mode_map = {"STABILIZE": 0, "AUTO": 3, "GUIDED": 4, "LOITER": 5, "RTL": 6, "LAND": 9}
        mode_name = str(req.params.get("mode", "GUIDED")).upper()
        mode_id   = _mode_map.get(mode_name, 4)
        connector.send_set_mode(mode_id)
        log.info("[%s] SET_MODE → %s (%d)", req.drone_id, mode_name, mode_id)
        return JSONResponse({"status": "sent", "drone_id": req.drone_id, "cmd": req.cmd})

    sysid = connector.get_state().get("sysid", 1)
    raw = mav.encode_command(sysid, req.cmd, req.params)
    if raw is None:
        return JSONResponse({"error": f"알 수 없는 명령: {req.cmd}"}, status_code=400)

    connector.send_command(raw)
    log.info("[%s] 명령 전송: %s %s", req.drone_id, req.cmd, req.params)

    # Attacker 화면에 명령 패킷 미러링 (↑ 방향)
    parsed = mav.decode(raw)
    if parsed:
        await att_mgr.broadcast({
            "type":      "packet",
            "direction": "up",
            "drone_id":  req.drone_id,
            "msg_id":    parsed.get("msg_id", 76),
            "msg_name":  parsed.get("msg_name", "COMMAND_LONG"),
            "hex":       raw.hex(),
            "fields":    _strip_meta(parsed),
        })

    return JSONResponse({"status": "sent", "drone_id": req.drone_id, "cmd": req.cmd})


# ── Static 파일 서빙 ──────────────────────────────────────────────────────────

app.mount("/attacker", StaticFiles(directory="frontend/attacker", html=True), name="attacker")
app.mount("/gcs",      StaticFiles(directory="frontend/gcs",      html=True), name="gcs")
