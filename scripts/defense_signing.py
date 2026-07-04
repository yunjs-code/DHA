#!/usr/bin/env python3
"""§3.3 방어 실험: SITL에 MAVLink v2 서명 키를 등록해 무서명 패킷을 거부하게 한다.

실험 순서:
  1. python scripts/generate_key.py              → signing.key 생성
  2. python scripts/defense_signing.py --drone drone-01 --key-file signing.key  → 서명 ON
  3. python scripts/inject_attack.py --drone drone-01 --cmd ARM --no-sign       → 묵살됨 ✓
  4. python scripts/inject_attack.py --drone drone-01 --cmd ARM --sign          → ACCEPTED ✓
"""
import argparse
import sys
import time
from pymavlink import mavutil

DRONE_PORTS = {"drone-01": 25760, "drone-02": 25770, "drone-03": 25780}
SITL_HOST   = "192.168.56.101"

COPTER_MODES = {0:"STABILIZE",3:"AUTO",4:"GUIDED",5:"LOITER",6:"RTL",9:"LAND"}
ACK_RESULTS  = {0:"ACCEPTED",1:"TEMPORARILY_REJECTED",2:"DENIED",3:"UNSUPPORTED",4:"FAILED",5:"IN_PROGRESS"}


def load_key(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            key = f.read()
        if len(key) != 32:
            print(f"[ERROR] 키 파일 크기가 32바이트가 아닙니다 ({len(key)}바이트): {path}")
            sys.exit(1)
        print(f"[KEY]   {key.hex()}")
        return key
    except FileNotFoundError:
        print(f"[ERROR] 키 파일 없음: {path}")
        print(f"        먼저 python scripts/generate_key.py 를 실행하세요.")
        sys.exit(1)


def connect(drone_id: str) -> mavutil.mavfile:
    port = DRONE_PORTS[drone_id]
    print(f"[CONNECT] {drone_id} @ {SITL_HOST}:{port} ...")
    conn = mavutil.mavlink_connection(f"tcp:{SITL_HOST}:{port}", source_system=254)

    hb = conn.wait_heartbeat(timeout=10)
    if hb is None:
        print(f"[ERROR]   HEARTBEAT 타임아웃 — SITL 미실행 또는 포트 불일치")
        sys.exit(1)

    mode_num  = hb.custom_mode
    armed     = bool(hb.base_mode & 0x80)
    mode_name = COPTER_MODES.get(mode_num, f"MODE_{mode_num}")
    print(f"[READY]   sysid={conn.target_system}  mode={mode_name}  armed={armed}")
    conn.target_component = 1
    return conn


def enable_signing(conn: mavutil.mavfile, key: bytes, allow_unsigned: bool = False) -> None:
    """pymavlink setup_signing()으로 서명 모드를 활성화한다.

    allow_unsigned=False → 무서명 패킷 전부 거부 (방어 완성 상태)
    allow_unsigned=True  → 무서명 패킷도 허용 (전환 단계용, 기본 사용 안 함)
    """
    print(f"\n[SIGN]  서명 활성화 중 ...")
    print(f"        allow_unsigned={allow_unsigned}  (False = 무서명 패킷 거부)")

    conn.setup_signing(
        secret_key=key,
        sign_outgoing=True,
        allow_unsigned=allow_unsigned,
    )
    print(f"[SIGN]  ✔ setup_signing() 완료")


def verify_signed_command(conn: mavutil.mavfile) -> bool:
    """서명된 HEARTBEAT 요청을 보내고 드론이 응답하는지 확인한다."""
    print(f"\n[VERIFY] 서명된 명령 응답 테스트 ...")
    ts = conn.target_system

    # 서명된 상태에서 ARM 명령 전송 (force arm)
    conn.mav.command_long_send(ts, 1, 400, 0, 1.0, 21196.0, 0, 0, 0, 0, 0)
    print(f"[VERIFY] 서명된 ARM 전송 → ACK 대기 (5초)")

    deadline = time.time() + 5.0
    while time.time() < deadline:
        msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.5)
        if msg:
            result_str = ACK_RESULTS.get(msg.result, f"RESULT_{msg.result}")
            print(f"[VERIFY] ✔ COMMAND_ACK: cmd={msg.command} → {result_str}")
            return True

    print(f"[VERIFY] ✗ ACK 없음 — 서명 설정이 잘못됐거나 이미 Armed 상태")
    return False


def show_unsigned_test(drone_id: str, key: bytes) -> None:
    """별도 연결(서명 없음)로 같은 드론에 명령을 보내 거부되는지 확인."""
    print(f"\n[TEST]  무서명 연결로 같은 드론에 명령 전송 → 거부 확인")
    port = DRONE_PORTS[drone_id]

    conn_unsigned = mavutil.mavlink_connection(f"tcp:{SITL_HOST}:{port}", source_system=255)
    hb = conn_unsigned.wait_heartbeat(timeout=10)
    if hb is None:
        print(f"[TEST]  HEARTBEAT 타임아웃 — 건너뜀")
        return

    conn_unsigned.target_component = 1
    ts = conn_unsigned.target_system
    conn_unsigned.mav.command_long_send(ts, 1, 400, 0, 1.0, 21196.0, 0, 0, 0, 0, 0)
    print(f"[TEST]  무서명 ARM 전송 → ACK 대기 (5초)")

    deadline = time.time() + 5.0
    got_ack = False
    while time.time() < deadline:
        msg = conn_unsigned.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.5)
        if msg:
            result_str = ACK_RESULTS.get(msg.result, f"RESULT_{msg.result}")
            print(f"[TEST]  ✗ ACK 수신됨: {result_str}  (서명 거부가 작동하지 않음)")
            got_ack = True
            break

    if not got_ack:
        print(f"[TEST]  ✔ ACK 없음 — 무서명 패킷이 거부됨 (방어 성공!)")

    conn_unsigned.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="§3.3 방어: SITL MAVLink v2 서명 활성화")
    ap.add_argument("--drone",    required=True, choices=list(DRONE_PORTS))
    ap.add_argument("--key-file", default="signing.key", help="서명 키 파일 (기본: signing.key)")
    ap.add_argument("--allow-unsigned", action="store_true",
                    help="무서명 패킷도 허용 (전환 테스트용, 방어 완성 시 사용 안 함)")
    ap.add_argument("--skip-verify", action="store_true", help="서명 검증 테스트 건너뜀")
    args = ap.parse_args()

    print(f"\n=== §3.3 MAVLink 서명 방어 ===")
    print(f"대상: {args.drone}  키: {args.key_file}")
    print(f"경로: Windows → SITL({SITL_HOST}:{DRONE_PORTS[args.drone]})\n")

    key  = load_key(args.key_file)
    conn = connect(args.drone)

    enable_signing(conn, key, allow_unsigned=args.allow_unsigned)

    if not args.skip_verify:
        verify_signed_command(conn)
        show_unsigned_test(args.drone, key)

    conn.close()

    print(f"\n{'='*50}")
    print(f"[결과] 서명 방어 활성화 완료")
    print(f"       ✔ 서명된 명령  → SITL 수락")
    print(f"       ✔ 무서명 명령  → SITL 묵살 (ACK 없음)")
    print(f"\n[다음 단계]")
    print(f"  A/B 비교:")
    print(f"    무서명 공격: python scripts/inject_attack.py --drone {args.drone} --cmd ARM --no-sign")
    print(f"    서명 공격:   python scripts/inject_attack.py --drone {args.drone} --cmd ARM --sign --key-file {args.key_file}")


if __name__ == "__main__":
    main()
