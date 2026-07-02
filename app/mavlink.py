"""MAVLink v2 바이너리 인코딩·디코딩 (순수 함수, side-effect 없음)."""
from __future__ import annotations

import struct
import logging

from pymavlink.dialects.v20 import ardupilotmega as _mav2

log = logging.getLogger(__name__)


def _msg_name_from_id(msg_id: int) -> str:
    """pymavlink 메시지 맵에서 msg_id → 메시지 이름 조회."""
    cls = _mav2.mavlink_map.get(msg_id)
    if cls and hasattr(cls, "msgname"):
        return cls.msgname
    return f"MSG_{msg_id}"

_MAV_STX    = 0xFD
_HDR_LEN    = 10   # STX(1)+LEN(1)+INCOMPAT(1)+COMPAT(1)+SEQ(1)+SYSID(1)+COMPID(1)+MSGID(3)
_CRC_LEN    = 2

_COPTER_MODES: dict[int, str] = {
    0:  "STABILIZE",    1:  "ACRO",        2:  "ALT_HOLD",    3:  "AUTO",
    4:  "GUIDED",       5:  "LOITER",      6:  "RTL",          7:  "CIRCLE",
    9:  "LAND",         11: "DRIFT",       13: "SPORT",        14: "FLIP",
    15: "AUTOTUNE",     16: "POSHOLD",     17: "BRAKE",        18: "THROW",
    19: "AVOID_ADSB",   20: "GUIDED_NOGPS",21: "SMART_RTL",   22: "FLOWHOLD",
    23: "FOLLOW",       24: "ZIGZAG",
}

_ACK_RESULTS: dict[int, str] = {
    0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
    3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS",
}

# SEQ 단조증가를 위해 모듈 레벨에서 단일 인스턴스 유지
_mav_instance = _mav2.MAVLink(None, srcSystem=255, srcComponent=0)


# ── 디코딩 ────────────────────────────────────────────────────────────────────

def decode(raw: bytes) -> dict | None:
    """MAVLink v2 패킷 바이너리 → dict. 파싱 실패 시 None 반환."""
    if len(raw) < _HDR_LEN + _CRC_LEN:
        return None
    if raw[0] != _MAV_STX:
        return None

    payload_len = raw[1]
    if len(raw) < _HDR_LEN + payload_len + _CRC_LEN:
        return None

    msg_id  = raw[7] | (raw[8] << 8) | (raw[9] << 16)
    payload = raw[_HDR_LEN: _HDR_LEN + payload_len]

    base = {
        "msg_id":  msg_id,
        "sysid":   raw[5],
        "compid":  raw[6],
    }

    try:
        if msg_id == 0:
            return base | _decode_heartbeat(payload)
        if msg_id == 1:
            return base | _decode_sys_status(payload)
        if msg_id == 33:
            return base | _decode_global_position_int(payload)
        if msg_id == 74:
            return base | _decode_vfr_hud(payload)
        if msg_id == 76:
            return base | _decode_command_long(payload)
        if msg_id == 77:
            return base | _decode_command_ack(payload)
        if msg_id == 193:
            return base | _decode_ekf_status_report(payload)
        return base | {"msg_name": _msg_name_from_id(msg_id)}
    except struct.error as exc:
        log.debug("decode struct error msg_id=%d: %s", msg_id, exc)
        return None


def _decode_heartbeat(p: bytes) -> dict:
    # wire order: custom_mode(u32), type(u8), autopilot(u8), base_mode(u8), system_status(u8), mavlink_version(u8)
    custom_mode, _, _, base_mode, _, _ = struct.unpack_from("<IBBBBB", p)
    return {
        "msg_name": "HEARTBEAT",
        "armed":    bool(base_mode & 0x80),
        "mode":     _COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}"),
    }


def _decode_sys_status(p: bytes) -> dict:
    # battery_remaining(i8)은 31 바이트 페이로드의 offset 30
    if len(p) < 31:
        return {"msg_name": "SYS_STATUS", "battery_pct": 100.0}
    batt = struct.unpack_from("<b", p, 30)[0]
    return {
        "msg_name":    "SYS_STATUS",
        "battery_pct": float(batt) if batt >= 0 else 100.0,
    }


def _decode_global_position_int(p: bytes) -> dict:
    # wire order: time_boot_ms(u32), lat(i32), lon(i32), alt(i32), relative_alt(i32),
    #             vx(i16), vy(i16), vz(i16), hdg(u16)
    _, lat, lon, alt, rel_alt, vx, vy, vz, hdg = struct.unpack_from("<IiiiihhhH", p)
    return {
        "msg_name":    "GLOBAL_POSITION_INT",
        "lat":         lat / 1e7,
        "lon":         lon / 1e7,
        "alt":         alt / 1000.0,
        "relative_alt": rel_alt / 1000.0,
        "vx":          vx  / 100.0,
        "vy":          vy  / 100.0,
        "vz":          vz  / 100.0,
        "hdg":         (hdg / 100.0) % 360.0,
    }


def _decode_vfr_hud(p: bytes) -> dict:
    # wire order: airspeed(f), groundspeed(f), alt(f), climb(f), heading(i16), throttle(u16)
    airspeed, groundspeed, alt, climb, heading, throttle = struct.unpack_from("<ffffhH", p)
    return {
        "msg_name":    "VFR_HUD",
        "airspeed":    round(airspeed, 2),
        "groundspeed": round(groundspeed, 2),
        "alt":         round(alt, 2),
        "climb":       round(climb, 2),
        "heading":     int(heading) % 360,
        "throttle":    int(throttle),
    }


def _decode_command_long(p: bytes) -> dict:
    # wire order: param1-7(f×7), command(u16), target_system(u8), target_component(u8), confirmation(u8)
    p1, p2, p3, p4, p5, p6, p7, command, tgt_sys, _, _ = struct.unpack_from("<fffffffHBBB", p)
    return {
        "msg_name":      "COMMAND_LONG",
        "command":       command,
        "target_system": tgt_sys,
        "params":        [round(v, 4) for v in (p1, p2, p3, p4, p5, p6, p7)],
    }


def _decode_command_ack(p: bytes) -> dict:
    command, result = struct.unpack_from("<HB", p)
    return {
        "msg_name":   "COMMAND_ACK",
        "command":    command,
        "result":     result,
        "result_str": _ACK_RESULTS.get(result, f"RESULT_{result}"),
    }


def _decode_ekf_status_report(p: bytes) -> dict:
    # payload: vel_var(f) pos_h_var(f) pos_v_var(f) compass_var(f) terrain_var(f) flags(H)
    if len(p) < 22:
        return {"msg_name": "EKF_STATUS_REPORT", "ekf_ok": False, "flags": 0}
    _, _, _, _, _, flags = struct.unpack_from("<fffffH", p)
    # EKF_STATUS_FLAGS 비트 정의 (MAVLink 표준):
    #   0x01 EKF_ATTITUDE, 0x02 EKF_VELOCITY_HORIZ, 0x04 EKF_VELOCITY_VERT
    #   0x08 EKF_POS_HORIZ_REL, 0x10 EKF_POS_HORIZ_ABS, 0x20 EKF_POS_VERT_ABS
    #   0x80 EKF_CONST_POS_MODE (GPS 없어서 제자리 고정 — 비행 불가)
    # GUIDED 비행 최소 조건: attitude+vel+pos 켜짐, CONST_POS_MODE 꺼짐
    ekf_ok = bool(
        (flags & 0x07) == 0x07 and   # EKF_ATTITUDE | EKF_VELOCITY_HORIZ | EKF_VELOCITY_VERT
        (flags & 0x18) and            # EKF_POS_HORIZ_REL(0x08) or EKF_POS_HORIZ_ABS(0x10)
        not (flags & 0x80)            # NOT EKF_CONST_POS_MODE (GPS 유실 시 켜짐)
    )
    return {"msg_name": "EKF_STATUS_REPORT", "ekf_ok": ekf_ok, "flags": int(flags)}


# ── 인코딩 ────────────────────────────────────────────────────────────────────

def encode_command(target_sysid: int, cmd: str, params: dict) -> bytes | None:
    """명령 문자열 → MAVLink v2 COMMAND_LONG 바이너리.

    지원 cmd: ARM | DISARM | TAKEOFF | LAND | RTL | GOTO
    params 예: {"alt": 30} / {"lat": 37.5, "lon": 126.9, "alt": 50}
    """
    p1 = p2 = p3 = p4 = p5 = p6 = p7 = 0.0

    if cmd == "ARM":
        mav_cmd = 400
        p1 = 1.0
        p2 = 21196.0  # force arm — SITL pre-arm 체크 우회
    elif cmd == "DISARM":
        mav_cmd = 400
        p1 = 0.0
        p2 = 21196.0  # force disarm
    elif cmd == "TAKEOFF":
        mav_cmd = 22
        p7 = float(params.get("alt", 30))
    elif cmd == "LAND":
        mav_cmd = 21
    elif cmd == "RTL":
        mav_cmd = 20
    elif cmd == "GOTO":
        mav_cmd = 192          # MAV_CMD_DO_REPOSITION
        p1 = float(params.get("speed", -1))
        p4 = float(params.get("yaw", -1))
        p5 = float(params.get("lat", 0))
        p6 = float(params.get("lon", 0))
        p7 = float(params.get("alt", 30))
    elif cmd == "SET_MODE":
        mav_cmd = 176          # MAV_CMD_DO_SET_MODE
        _mode_map = {
            "STABILIZE": 0, "AUTO": 3, "GUIDED": 4,
            "LOITER": 5,    "RTL": 6,  "LAND": 9,
        }
        mode_name = str(params.get("mode", "GUIDED")).upper()
        p1 = 1.0               # MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        p2 = float(_mode_map.get(mode_name, 4))
    else:
        log.warning("encode_command: 알 수 없는 명령 '%s'", cmd)
        return None

    try:
        msg = _mav_instance.command_long_encode(
            target_sysid, 1,        # target_system, target_component
            mav_cmd, 0,             # command, confirmation
            p1, p2, p3, p4, p5, p6, p7,
        )
        return bytes(msg.pack(_mav_instance))
    except Exception as exc:
        log.error("encode_command 실패 cmd=%s: %s", cmd, exc)
        return None
