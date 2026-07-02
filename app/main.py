"""FastAPI WebSocket 허브 — GCS·Attacker 브라우저와 SITL 연결."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
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
    "drone-01": SITLConnector("drone-01", 5760),
    "drone-02": SITLConnector("drone-02", 5770),
    "drone-03": SITLConnector("drone-03", 5780),
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

        for drone_id, connector in list(DRONES.items()):

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

            # GCS: COMMAND_ACK 결과 전달
            for ack in connector.drain_acks():
                await gcs_mgr.broadcast({
                    "type":     "cmd_ack",
                    "drone_id": ack["drone_id"],
                    "cmd":      ack["cmd"],
                    "result":   ack["result"],
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
                "vx":           s.get("vx", 0.0),
                "vy":           s.get("vy", 0.0),
                "vz":           s.get("vz", 0.0),
                "climb":        s.get("climb", 0.0),
                "heading":      s.get("heading", s.get("hdg", 0)),
                "battery_pct":  s.get("battery_pct", 100.0),
                "armed":        s.get("armed", False),
                "mode":         s.get("mode", ""),
                "connected":    s.get("connected", False),
                "ekf_ok":       s.get("ekf_ok", False),
            })


def _strip_meta(parsed: dict) -> dict:
    return {k: v for k, v in parsed.items()
            if k not in ("msg_id", "sysid", "compid", "msg_name")}


# ── FastAPI 앱 ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 로그 레벨을 INFO로 설정 (DEBUG 메시지 포함 시 DEBUG로 변경)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    log.info("=" * 60)
    log.info("UAV Security Testbed 시작")
    log.info("드론 목록:")
    for drone_id, c in DRONES.items():
        log.info("  %s → TCP %s:%d", drone_id, os.environ.get("SITL_HOST", "127.0.0.1"), c.tcp_port)
    log.info("=" * 60)
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
    log.info("[API] 명령 수신: drone=%s cmd=%s params=%s", req.drone_id, req.cmd, req.params)

    connector = DRONES.get(req.drone_id)
    if connector is None:
        log.error("[API] 알 수 없는 드론: %s", req.drone_id)
        return JSONResponse({"error": f"알 수 없는 드론: {req.drone_id}"}, status_code=404)

    state = connector.get_state()
    log.info("[API] 현재 상태: ready=%s connected=%s armed=%s mode=%s",
             connector.is_ready(), state.get("connected"), state.get("armed"), state.get("mode"))

    if not connector.is_ready():
        log.warning("[API] SITL 미연결 — 명령 거부: %s", req.cmd)
        return JSONResponse({"error": "SITL 미연결"}, status_code=503)

    # SET_MODE는 네이티브 set_mode_send 사용
    if req.cmd == "SET_MODE":
        _mode_map = {"STABILIZE": 0, "AUTO": 3, "GUIDED": 4, "LOITER": 5, "RTL": 6, "LAND": 9}
        mode_name = str(req.params.get("mode", "GUIDED")).upper()
        mode_id   = _mode_map.get(mode_name, 4)
        log.info("[API] SET_MODE: %s → mode_id=%d", mode_name, mode_id)
        connector.send_set_mode(mode_id)
        return JSONResponse({"status": "sent", "drone_id": req.drone_id, "cmd": req.cmd})

    sysid = state.get("sysid", 1)
    # GOTO는 SET_POSITION_TARGET_GLOBAL_INT 사용 (DO_REPOSITION은 미지원)
    if req.cmd == "GOTO":
        lat = float(req.params.get("lat", 0))
        lon = float(req.params.get("lon", 0))
        alt = float(req.params.get("alt", 30))
        log.info("[API] GOTO → lat=%.6f lon=%.6f alt=%.1fm", lat, lon, alt)
        connector.send_goto(lat, lon, alt)
        return JSONResponse({"status": "sent", "drone_id": req.drone_id, "cmd": req.cmd})

    log.info("[API] encode_command: cmd=%s sysid=%d params=%s", req.cmd, sysid, req.params)
    raw = mav.encode_command(sysid, req.cmd, req.params)
    if raw is None:
        log.error("[API] encode_command 실패: cmd=%s", req.cmd)
        return JSONResponse({"error": f"알 수 없는 명령: {req.cmd}"}, status_code=400)

    log.info("[API] SITL로 전송 중: %s %d bytes", req.cmd, len(raw))
    connector.send_command(raw)

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
