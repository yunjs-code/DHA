"""SITL 커넥터 — pymavlink TCP 직접 연결, 원본 바이너리 보존.

서버가 SITL ArduCopter TCP 포트에 직접 접속 (MAVProxy 불필요).
드론별 TCP 포트: 5760(drone-01), 5761(drone-02), 5762(drone-03)
"""
from __future__ import annotations

import collections
import logging
import math
import struct
import threading
import time
from typing import Optional

from pymavlink import mavutil

from app import mavlink as mav

log = logging.getLogger(__name__)

_RECV_TIMEOUT    = 1.0   # recv_match 블로킹 타임아웃 (초)
_RECONNECT_DELAY = 5     # SITL 무응답 후 재시도 대기 (초)
_QUEUE_MAXLEN    = 100   # 원본 바이너리 큐 최대 크기
_SITL_TIMEOUT    = 30    # 이 시간 동안 패킷 없으면 재연결 간주 (초)
_HB_TIMEOUT      = 30    # wait_heartbeat 타임아웃 (초)

_CMD_NAMES = {
    400: "ARM/DISARM", 22: "TAKEOFF", 21: "LAND",
    20: "RTL", 192: "DO_REPOSITION(GOTO)", 176: "DO_SET_MODE",
}

_ACK_RESULTS = {
    0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
    3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS",
}


class SITLConnector:
    """단일 ArduPilot SITL 인스턴스와의 MAVLink v2 TCP 직접 연결."""

    def __init__(self, drone_id: str, tcp_port: int) -> None:
        self.drone_id = drone_id
        self.tcp_port = tcp_port

        self._conn: Optional[mavutil.mavfile] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop = threading.Event()

        self._raw_queue: collections.deque[bytes] = collections.deque(maxlen=_QUEUE_MAXLEN)
        self._ack_queue: collections.deque[dict] = collections.deque(maxlen=50)

        self._state: dict = {
            "drone_id":  drone_id,
            "connected": False,
        }
        self._last_armed: Optional[bool] = None  # armed 상태 변화 추적

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._recv_loop,
            name=f"sitl-{self.drone_id}",
            daemon=True,
        )
        self._thread.start()
        log.info("[%s] 수신 스레드 시작 → TCP 127.0.0.1:%d", self.drone_id, self.tcp_port)

    def stop(self) -> None:
        """수신 스레드를 정지하고 연결을 해제한다."""
        self._stop.set()
        self._ready.clear()
        with self._lock:
            conn = self._conn
            self._conn = None
            self._state["connected"] = False
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        log.info("[%s] 커넥터 정지 완료", self.drone_id)

    def recv_raw(self) -> Optional[bytes]:
        with self._lock:
            return self._raw_queue[-1] if self._raw_queue else None

    def drain_raw(self) -> list[bytes]:
        with self._lock:
            packets = list(self._raw_queue)
            self._raw_queue.clear()
            return packets

    def drain_acks(self) -> list[dict]:
        """쌓인 COMMAND_ACK 결과를 꺼내서 반환."""
        with self._lock:
            acks = list(self._ack_queue)
            self._ack_queue.clear()
            return acks

    def get_state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def send_command(self, raw: bytes) -> None:
        """COMMAND_LONG을 SITL에 전송 — 항상 command_long_send 사용."""
        if self._conn is None:
            log.warning("[%s] send_command: 연결 없음 — 명령 무시됨!", self.drone_id)
            return
        try:
            if len(raw) >= 10 and raw[0] == 0xFD:
                msg_id  = raw[7] | (raw[8] << 8) | (raw[9] << 16)
                if msg_id == 76:  # COMMAND_LONG
                    payload = raw[10: 10 + raw[1]]
                    # MAVLink v2는 trailing zero를 제거하므로 33바이트로 zero-padding
                    padded = payload + b'\x00' * max(0, 33 - len(payload))
                    p1, p2, p3, p4, p5, p6, p7, cmd_id, tgt_sys, _, _ = \
                        struct.unpack_from("<fffffffHBBB", padded)
                    cmd_name = _CMD_NAMES.get(cmd_id, f"cmd#{cmd_id}")
                    log.info(
                        "[%s] ▶ 명령 전송: %s (cmd_id=%d) "
                        "tgt_sys=%d p1=%.1f p2=%.1f p5=%.6f p6=%.6f p7=%.1f",
                        self.drone_id, cmd_name, cmd_id, tgt_sys,
                        p1, p2, p5, p6, p7,
                    )
                    self._conn.mav.command_long_send(
                        tgt_sys, 0, cmd_id, 0,
                        p1, p2, p3, p4, p5, p6, p7,
                    )
                    return
            log.warning("[%s] 알 수 없는 패킷 형식 (len=%d, stx=0x%02x) — 전송 건너뜀",
                        self.drone_id, len(raw), raw[0] if raw else 0)
        except Exception as exc:
            log.error("[%s] send_command 실패: %s", self.drone_id, exc)

    def send_goto(self, lat: float, lon: float, alt: float) -> None:
        """SET_POSITION_TARGET_GLOBAL_INT으로 GOTO 전송 (GUIDED 모드 전용).

        MAV_CMD_DO_REPOSITION(192)는 일부 ArduCopter 버전에서 UNSUPPORTED 반환.
        QGC와 동일한 방식으로 position target을 직접 설정한다.
        """
        if self._conn is None:
            log.warning("[%s] send_goto: 연결 없음!", self.drone_id)
            return
        try:
            type_mask = (
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
            )
            self._conn.mav.set_position_target_global_int_send(
                0,                          # time_boot_ms (ignored)
                self._conn.target_system,   # target_system
                0,                          # target_component
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                type_mask,
                int(lat * 1e7),             # lat_int
                int(lon * 1e7),             # lon_int
                float(alt),                 # alt (m, 홈 기준 상대고도)
                0.0, 0.0, 0.0,              # vx, vy, vz (무시)
                0.0, 0.0, 0.0,              # afx, afy, afz (무시)
                0.0, 0.0,                   # yaw, yaw_rate (무시)
            )
            log.info("[%s] ▶ GOTO (SET_POSITION_TARGET_GLOBAL_INT) lat=%.6f lon=%.6f alt=%.1fm",
                     self.drone_id, lat, lon, alt)
        except Exception as exc:
            log.error("[%s] send_goto 실패: %s", self.drone_id, exc)

    def send_set_mode(self, mode_id: int) -> None:
        if self._conn is None:
            log.warning("[%s] send_set_mode: 연결 없음!", self.drone_id)
            return
        try:
            log.info("[%s] ▶ SET_MODE 전송: custom_mode=%d (target_system=%d)",
                     self.drone_id, mode_id, self._conn.target_system)
            self._conn.mav.set_mode_send(
                self._conn.target_system,
                1,       # MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                mode_id,
            )
        except Exception as exc:
            log.error("[%s] send_set_mode 실패: %s", self.drone_id, exc)

    def is_ready(self) -> bool:
        return self._ready.is_set()

    # ── 내부 수신 루프 ─────────────────────────────────────────────────────────

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            log.info("[%s] ━━ TCP 접속 시도: 127.0.0.1:%d ━━", self.drone_id, self.tcp_port)
            try:
                conn = mavutil.mavlink_connection(
                    f"tcp:127.0.0.1:{self.tcp_port}",
                    source_system=255,
                )
                log.info("[%s] TCP 소켓 연결됨 — HEARTBEAT 대기 중 (최대 %ds)...",
                         self.drone_id, _HB_TIMEOUT)
                with self._lock:
                    self._conn = conn
                self._run(conn)
            except ConnectionRefusedError:
                log.warning("[%s] ✗ 연결 거부됨 — SITL이 실행 중인지 확인 필요 (TCP:%d). %ds 후 재시도",
                            self.drone_id, self.tcp_port, _RECONNECT_DELAY)
                with self._lock:
                    self._state["connected"] = False
                    self._conn = None
                time.sleep(_RECONNECT_DELAY)
            except Exception as exc:
                log.warning("[%s] ✗ 연결 실패 (%s). %ds 후 재시도",
                            self.drone_id, exc, _RECONNECT_DELAY)
                with self._lock:
                    self._state["connected"] = False
                    self._conn = None
                time.sleep(_RECONNECT_DELAY)

    def _run(self, conn: mavutil.mavfile) -> None:
        """HEARTBEAT 수신 후 데이터 스트림 요청 → 수신 루프."""
        hb = conn.wait_heartbeat(blocking=True, timeout=_HB_TIMEOUT)
        if hb is None:
            raise RuntimeError(f"HEARTBEAT 타임아웃 ({_HB_TIMEOUT}s) — SITL 미실행 또는 TCP 포트 불일치")

        sysid = conn.target_system
        with self._lock:
            self._state["sysid"] = sysid

        raw = bytes(hb.get_msgbuf())
        parsed_hb = mav.decode(raw) if raw else None
        armed = parsed_hb.get("armed", False) if parsed_hb else False
        mode  = parsed_hb.get("mode", "?")    if parsed_hb else "?"

        log.info(
            "[%s] ✔ HEARTBEAT 수신! sysid=%d armed=%s mode=%s",
            self.drone_id, sysid, armed, mode,
        )

        if raw:
            with self._lock:
                self._raw_queue.append(raw)
                self._state["connected"] = True
                if parsed_hb:
                    self._merge_state(parsed_hb)
            self._ready.set()

        conn.mav.request_data_stream_send(
            sysid, conn.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            10,  # 10 Hz
            1,   # start
        )
        log.info("[%s] ★ SITL 연결 완료 (TCP:%d, sysid=%d) — 데이터 스트림 요청 완료",
                 self.drone_id, self.tcp_port, sysid)

        last_recv = time.time()
        msg_counts: dict[int, int] = {}

        while not self._stop.is_set():
            try:
                msg = conn.recv_match(blocking=True, timeout=_RECV_TIMEOUT)
            except Exception as exc:
                if self._stop.is_set():
                    return
                log.debug("[%s] recv_match 예외: %s", self.drone_id, exc)
                raise

            if msg is None:
                elapsed = time.time() - last_recv
                if elapsed > _SITL_TIMEOUT:
                    raise RuntimeError(f"SITL 패킷 없음 {elapsed:.0f}s — 재연결")
                continue

            last_recv = time.time()
            raw = bytes(msg.get_msgbuf())
            if not raw:
                continue

            msg_id = msg.get_msgId()
            msg_counts[msg_id] = msg_counts.get(msg_id, 0) + 1

            parsed = mav.decode(raw)
            with self._lock:
                self._raw_queue.append(raw)
                self._state["connected"] = True
                if parsed:
                    self._merge_state(parsed)
            self._ready.set()

            # COMMAND_ACK — 명령 수락/거부 결과 (항상 WARNING 이상으로 출력)
            if msg_id == 77 and parsed:
                cmd_id     = parsed.get("command", -1)
                result_raw = parsed.get("result", -1)
                result_str = _ACK_RESULTS.get(result_raw, f"RESULT_{result_raw}")
                cmd_name   = _CMD_NAMES.get(cmd_id, f"cmd#{cmd_id}")
                log.warning(
                    "[%s] ◀ COMMAND_ACK: %s → %s (cmd=%d result=%d)",
                    self.drone_id, cmd_name, result_str, cmd_id, result_raw,
                )
                with self._lock:
                    self._ack_queue.append({
                        "drone_id": self.drone_id,
                        "cmd_id":   cmd_id,
                        "cmd":      cmd_name,
                        "result":   result_str,
                        "ok":       result_raw == 0,
                    })

            # 주기적 상태 요약 (매 500번째 패킷)
            total = sum(msg_counts.values())
            if total % 500 == 0:
                with self._lock:
                    s = dict(self._state)
                log.info(
                    "[%s] 상태 요약: armed=%s mode=%s "
                    "lat=%.4f lon=%.4f rel_alt=%.1fm 수신패킷=%d",
                    self.drone_id,
                    s.get("armed", "?"), s.get("mode", "?"),
                    s.get("lat", 0.0), s.get("lon", 0.0),
                    s.get("relative_alt", 0.0), total,
                )

    def _merge_state(self, parsed: dict) -> None:
        """파싱 결과를 누적 상태 dict에 병합 (반드시 _lock 안에서 호출)."""
        msg_name = parsed.get("msg_name", "")

        if msg_name == "HEARTBEAT":
            new_armed = parsed.get("armed", False)
            new_mode  = parsed.get("mode", "")
            old_armed = self._state.get("armed")
            self._state["armed"] = new_armed
            self._state["mode"]  = new_mode
            # armed 상태 변화 시 항상 로그
            if old_armed != new_armed:
                log.info("[%s] ★ armed 상태 변경: %s → %s (mode=%s)",
                         self.drone_id, old_armed, new_armed, new_mode)

        elif msg_name == "SYS_STATUS":
            self._state["battery_pct"] = parsed.get("battery_pct", 100.0)

        elif msg_name == "GLOBAL_POSITION_INT":
            vx_ms = parsed.get("vx", 0.0)
            vy_ms = parsed.get("vy", 0.0)
            vz_ms = parsed.get("vz", 0.0)
            self._state["lat"]          = parsed.get("lat", 0.0)
            self._state["lon"]          = parsed.get("lon", 0.0)
            self._state["alt"]          = parsed.get("alt", 0.0)
            self._state["relative_alt"] = parsed.get("relative_alt", 0.0)
            self._state["vx"]           = vx_ms
            self._state["vy"]           = vy_ms
            self._state["vz"]           = vz_ms
            self._state["hdg"]          = parsed.get("hdg", 0.0)
            # VFR_HUD groundspeed 미수신 또는 0일 때 vx/vy로 대체
            if not self._state.get("groundspeed"):
                self._state["groundspeed"] = round(math.sqrt(vx_ms**2 + vy_ms**2), 2)

        elif msg_name == "VFR_HUD":
            self._state["airspeed"]     = parsed.get("airspeed", 0.0)
            self._state["groundspeed"]  = parsed.get("groundspeed", 0.0)
            self._state["heading"]      = parsed.get("heading", 0)
            self._state["throttle"]     = parsed.get("throttle", 0)
            self._state["climb"]        = parsed.get("climb", 0.0)

        elif msg_name == "EKF_STATUS_REPORT":
            prev = self._state.get("ekf_ok")
            new  = parsed.get("ekf_ok", False)
            self._state["ekf_ok"]    = new
            self._state["ekf_flags"] = parsed.get("flags", 0)
            if prev is not True and new is True:
                log.info("[%s] ★ EKF 준비 완료 (flags=0x%03x)", self.drone_id, parsed.get("flags", 0))
