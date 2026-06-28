"""SITL 커넥터 — pymavlink UDP 수신·송신, 원본 바이너리 보존.

SITL이 UDP 클라이언트로 서버에 패킷을 전송하면 서버가 수신 대기.
드론별 UDP 포트: 14560(drone-01), 14570(drone-02), 14580(drone-03)
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Optional

from pymavlink import mavutil

from app import mavlink as mav

log = logging.getLogger(__name__)

_RECV_TIMEOUT    = 1.0   # recv_match 블로킹 타임아웃 (초)
_RECONNECT_DELAY = 5    # SITL 무응답 후 재시도 대기 (초)
_QUEUE_MAXLEN    = 100  # 원본 바이너리 큐 최대 크기
_SITL_TIMEOUT    = 30   # 이 시간 동안 패킷 없으면 재연결 간주 (초)
_HB_TIMEOUT      = 30   # wait_heartbeat 타임아웃 (MAVProxy 부팅 대기)


class SITLConnector:
    """단일 ArduPilot SITL 인스턴스와의 MAVLink v2 UDP 연결.

    start() 로 백그라운드 스레드를 시작하면 SITL UDP 포트에서 패킷을
    수신하여 _raw_queue 와 _state 에 누적한다.
    UDP 소켓은 최초 1회만 바인딩하고 유지한다.
    """

    def __init__(self, drone_id: str, udp_port: int) -> None:
        self.drone_id = drone_id
        self.udp_port = udp_port

        self._conn: Optional[mavutil.mavfile] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

        self._raw_queue: collections.deque[bytes] = collections.deque(maxlen=_QUEUE_MAXLEN)

        self._state: dict = {
            "drone_id":  drone_id,
            "connected": False,
        }

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def start(self) -> None:
        """백그라운드 수신 스레드를 시작한다 (중복 호출 무시)."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._recv_loop,
            name=f"sitl-{self.drone_id}",
            daemon=True,
        )
        self._thread.start()
        log.info("[%s] 수신 스레드 시작 (UDP 0.0.0.0:%d)", self.drone_id, self.udp_port)

    def recv_raw(self) -> Optional[bytes]:
        """가장 최근에 수신된 패킷의 원본 바이너리를 반환 (큐 소비 없음)."""
        with self._lock:
            return self._raw_queue[-1] if self._raw_queue else None

    def drain_raw(self) -> list[bytes]:
        """큐에 쌓인 모든 원본 바이너리를 꺼내서 반환 (큐를 비운다)."""
        with self._lock:
            packets = list(self._raw_queue)
            self._raw_queue.clear()
            return packets

    def get_state(self) -> dict:
        """파싱된 최신 드론 상태 dict 반환 (복사본)."""
        with self._lock:
            return dict(self._state)

    def send_command(self, raw: bytes) -> None:
        """COMMAND_LONG을 SITL에 전송 — pymavlink native 방식."""
        if self._conn is None:
            log.warning("[%s] send_command: 아직 연결 없음", self.drone_id)
            return
        try:
            if len(raw) >= 10 and raw[0] == 0xFD:
                import struct
                msg_id  = raw[7] | (raw[8] << 8) | (raw[9] << 16)
                payload = raw[10: 10 + raw[1]]
                if msg_id == 76 and len(payload) >= 33:  # COMMAND_LONG
                    p1, p2, p3, p4, p5, p6, p7, cmd_id, tgt_sys, _, _ = \
                        struct.unpack_from("<fffffffHBBB", payload)
                    self._conn.mav.command_long_send(
                        tgt_sys, 0, cmd_id, 0,
                        p1, p2, p3, p4, p5, p6, p7,
                    )
                    log.info("[%s] → cmd_id=%d p1=%.0f p2=%.0f 전송", self.drone_id, cmd_id, p1, p2)
                    return
            self._conn.write(raw)
            log.info("[%s] → %d bytes 전송", self.drone_id, len(raw))
        except Exception as exc:
            log.error("[%s] send_command 실패: %s", self.drone_id, exc)

    def send_set_mode(self, mode_id: int) -> None:
        """네이티브 SET_MODE 메시지로 비행 모드 변경."""
        if self._conn is None:
            log.warning("[%s] send_set_mode: 아직 연결 없음", self.drone_id)
            return
        try:
            self._conn.mav.set_mode_send(
                self._conn.target_system,
                1,          # MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                mode_id,
            )
            log.info("[%s] → SET_MODE custom_mode=%d 전송", self.drone_id, mode_id)
        except Exception as exc:
            log.error("[%s] send_set_mode 실패: %s", self.drone_id, exc)

    def is_ready(self) -> bool:
        """첫 패킷을 수신했으면 True."""
        return self._ready.is_set()

    # ── 내부 수신 루프 ─────────────────────────────────────────────────────────

    def _recv_loop(self) -> None:
        """UDP 소켓을 한 번 바인딩 후 유지 — SITL 재시작에도 소켓 재사용."""
        log.info("[%s] UDP 0.0.0.0:%d 수신 대기 (SITL 시작 기다리는 중...)", self.drone_id, self.udp_port)
        conn = mavutil.mavlink_connection(
            f"udpin:0.0.0.0:{self.udp_port}",
            source_system=255,
        )
        with self._lock:
            self._conn = conn

        while True:
            try:
                self._run(conn)
            except Exception as exc:
                log.warning("[%s] SITL 무응답, %ds 후 재시도: %s", self.drone_id, _RECONNECT_DELAY, exc)
                with self._lock:
                    self._state["connected"] = False
                time.sleep(_RECONNECT_DELAY)

    def _run(self, conn: mavutil.mavfile) -> None:
        """HEARTBEAT 수신 후 데이터 스트림 요청 → 수신 루프."""
        hb = conn.wait_heartbeat(blocking=True, timeout=_HB_TIMEOUT)
        if hb is None:
            raise RuntimeError("HEARTBEAT 타임아웃 — SITL/MAVProxy 미실행")

        with self._lock:
            self._state["sysid"] = conn.target_system

        raw = bytes(hb.get_msgbuf())
        if raw:
            parsed = mav.decode(raw)
            with self._lock:
                self._raw_queue.append(raw)
                self._state["connected"] = True
                if parsed:
                    self._merge_state(parsed)
            self._ready.set()

        conn.mav.request_data_stream_send(
            conn.target_system,
            conn.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            10,  # 10 Hz
            1,   # start
        )
        log.info("[%s] SITL 연결됨 (UDP :%d, sysid=%d)", self.drone_id, self.udp_port, conn.target_system)

        last_recv = time.time()
        while True:
            try:
                msg = conn.recv_match(blocking=True, timeout=_RECV_TIMEOUT)
            except Exception as exc:
                log.debug("[%s] recv_match 예외: %s", self.drone_id, exc)
                raise

            if msg is None:
                # SITL이 일정 시간 이상 무응답이면 재연결 (wait_heartbeat 재시도)
                if time.time() - last_recv > _SITL_TIMEOUT:
                    raise RuntimeError("SITL 패킷 없음 — 재연결")
                continue

            last_recv = time.time()
            raw = bytes(msg.get_msgbuf())
            if not raw:
                continue

            parsed = mav.decode(raw)
            with self._lock:
                self._raw_queue.append(raw)
                self._state["connected"] = True
                if parsed:
                    self._merge_state(parsed)

            self._ready.set()
            log.debug("[%s] 수신 msg_id=%d len=%d", self.drone_id, msg.get_msgId(), len(raw))

    def _merge_state(self, parsed: dict) -> None:
        """파싱 결과를 누적 상태 dict에 병합 (반드시 _lock 안에서 호출)."""
        msg_name = parsed.get("msg_name", "")

        if msg_name == "HEARTBEAT":
            self._state["armed"] = parsed.get("armed", False)
            self._state["mode"]  = parsed.get("mode", "")

        elif msg_name == "SYS_STATUS":
            self._state["battery_pct"] = parsed.get("battery_pct", 100.0)

        elif msg_name == "GLOBAL_POSITION_INT":
            self._state["lat"]          = parsed.get("lat", 0.0)
            self._state["lon"]          = parsed.get("lon", 0.0)
            self._state["alt"]          = parsed.get("alt", 0.0)
            self._state["relative_alt"] = parsed.get("relative_alt", 0.0)
            self._state["vx"]           = parsed.get("vx", 0.0)
            self._state["vy"]           = parsed.get("vy", 0.0)
            self._state["vz"]           = parsed.get("vz", 0.0)
            self._state["hdg"]          = parsed.get("hdg", 0.0)

        elif msg_name == "VFR_HUD":
            self._state["airspeed"]     = parsed.get("airspeed", 0.0)
            self._state["groundspeed"]  = parsed.get("groundspeed", 0.0)
            self._state["heading"]      = parsed.get("heading", 0)
            self._state["throttle"]     = parsed.get("throttle", 0)
            self._state["climb"]        = parsed.get("climb", 0.0)
