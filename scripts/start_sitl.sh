#!/bin/bash
# UAV 테스트베드 전체 스택 실행: SITL N대 + TCP 릴레이 + FastAPI 서버
# 헤드리스 직접 실행 (Gazebo/외부 FDM 불필요, ArduCopter 내장 물리 모델 사용)
# sim_vehicle.py 미사용 — GUI 터미널 불필요
# 사용법: bash scripts/start_sitl.sh [대수=3]

set -e

N=${1:-3}
ARDUPILOT_DIR="$HOME/ardupilot"
BINARY="$ARDUPILOT_DIR/build/sitl/bin/arducopter"
LOG_DIR="/tmp"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_ARG="quad"   # ArduCopter 내장 물리 모델 (외부 FDM/Gazebo 불필요, GPS/EKF가 즉시 수렴)

if [ ! -f "$BINARY" ]; then
    echo "[ERROR] ArduCopter 바이너리 없음: $BINARY"
    echo "        빌드: cd $ARDUPILOT_DIR && ./waf configure --board sitl && ./waf copter"
    exit 1
fi

RELAY_SCRIPT="$(dirname "$0")/mavlink_tcp_relay.py"
if [ ! -f "$RELAY_SCRIPT" ]; then
    echo "[ERROR] 릴레이 스크립트 없음: $RELAY_SCRIPT"
    exit 1
fi

# 기존 프로세스 정리
echo "[INFO] 기존 프로세스 정리..."
pkill -f 'arducopter'         2>/dev/null || true
pkill -f 'mavlink_tcp_relay'  2>/dev/null || true
pkill -f 'uvicorn app.main'   2>/dev/null || true
sleep 2

source "$HOME/venv-ardupilot/bin/activate" 2>/dev/null || true

echo "[INFO] SITL ${N}대 시작 (헤드리스, model=${MODEL_ARG})"
echo ""

FAILED_DRONES=()

for i in $(seq 0 $((N - 1))); do
    DRONE_NUM=$((i + 1))
    ARDU_PORT=$((5760 + i * 10))      # ArduCopter 내부 TCP 포트
    SERVER_PORT=$((15760 + i * 10))   # FastAPI 서버 접속용
    ATTACK_PORT=$((25760 + i * 10))   # 공격 스크립트 접속용
    WORK_DIR="$LOG_DIR/sitl_drone-0${DRONE_NUM}"
    ARDU_LOG="$LOG_DIR/arducopter_drone-0${DRONE_NUM}.log"
    MAV_LOG="$LOG_DIR/mavproxy_drone-0${DRONE_NUM}.log"

    mkdir -p "$WORK_DIR"

    # SYSID_THISMAV를 인스턴스별로 고유하게 지정 (기본값 그대로 두면 3대 전부
    # sysid=1이 되어 duplicate_sysid 룰이 drone-02/03을 영구히 "사칭"으로
    # 오탐, Blue Agent가 정상 GCS 명령까지 차단하는 원인이 됨).
    DEFAULTS_FILE="$WORK_DIR/default_params.parm"
    echo "SYSID_THISMAV ${DRONE_NUM}" > "$DEFAULTS_FILE"

    # ── 1단계: ArduCopter 직접 실행 ─────────────────────────────────────────
    echo "[STEP] drone-0${DRONE_NUM}: ArduCopter 시작 (TCP:${ARDU_PORT}, model=${MODEL_ARG}, sysid=${DRONE_NUM})"
    (
        cd "$WORK_DIR"
        "$BINARY" \
            --model "$MODEL_ARG" \
            --speedup=1 \
            -I "$i" \
            --home "37.566535,126.977969,0.0,0.0" \
            --wipe \
            --defaults "$DEFAULTS_FILE" \
            > "$ARDU_LOG" 2>&1
    ) &
    ARDU_PID=$!
    echo "       ArduCopter PID=${ARDU_PID}  로그: $ARDU_LOG"

    # ── 2단계: TCP 포트 오픈 대기 (최대 40초) ───────────────────────────────
    echo -n "       TCP:${ARDU_PORT} 오픈 대기 "
    WAITED=0
    PORT_OPEN=0
    while [ $WAITED -lt 40 ]; do
        sleep 1
        WAITED=$((WAITED + 1))
        if ss -tlnp 2>/dev/null | grep -q ":${ARDU_PORT}"; then
            echo "  ✔ OK (${WAITED}초)"
            PORT_OPEN=1
            break
        fi
        printf "."
    done

    if [ $PORT_OPEN -eq 0 ]; then
        echo "  ✗ 타임아웃 (${WAITED}초) — drone-0${DRONE_NUM} ArduCopter 시작 실패"
        echo "  로그 확인: tail $ARDU_LOG"
        FAILED_DRONES+=("drone-0${DRONE_NUM} (ArduCopter TCP:${ARDU_PORT} 미기동)")
        continue
    fi

    # ── 3단계: Python TCP 릴레이 시작 (MAVProxy 대체) ──────────────────────
    echo "       릴레이 시작: TCP:${ARDU_PORT} → SERVER:${SERVER_PORT} / ATTACK:${ATTACK_PORT}"
    python3 "$RELAY_SCRIPT" \
        --ardu-port "${ARDU_PORT}" \
        --listen "${SERVER_PORT}" "${ATTACK_PORT}" \
        > "$MAV_LOG" 2>&1 &
    RELAY_PID=$!
    echo "       릴레이 PID=${RELAY_PID}  로그: $MAV_LOG"

    # ── 4단계: 릴레이 포트 오픈 확인 (최대 10초) ────────────────────────────
    echo -n "       SERVER:${SERVER_PORT} / ATTACK:${ATTACK_PORT} 오픈 대기 "
    WAITED=0
    RELAY_OK=0
    while [ $WAITED -lt 10 ]; do
        if ! kill -0 "$RELAY_PID" 2>/dev/null; then
            echo "  ✗ 릴레이 프로세스 조기 종료 (${WAITED}초)"
            echo "  로그 확인: tail $MAV_LOG"
            break
        fi
        if ss -tlnp 2>/dev/null | grep -q ":${SERVER_PORT}" \
           && ss -tlnp 2>/dev/null | grep -q ":${ATTACK_PORT}"; then
            echo "  ✔ OK (${WAITED}초)"
            RELAY_OK=1
            break
        fi
        sleep 1
        WAITED=$((WAITED + 1))
        printf "."
    done

    if [ $RELAY_OK -eq 0 ]; then
        echo "  ✗ 타임아웃 (${WAITED}초) — drone-0${DRONE_NUM} 릴레이 포트 오픈 실패"
        echo "  로그 확인: tail $MAV_LOG"
        FAILED_DRONES+=("drone-0${DRONE_NUM} (릴레이 SERVER:${SERVER_PORT}/ATTACK:${ATTACK_PORT} 미기동)")
    fi
    echo ""

    sleep 2
done

echo "================================================================"
if [ ${#FAILED_DRONES[@]} -gt 0 ]; then
    echo "[ERROR] ${#FAILED_DRONES[@]}대 SITL 연결 실패:"
    for f in "${FAILED_DRONES[@]}"; do
        echo "  - $f"
    done
    echo "================================================================"
    exit 1
fi

echo "[INFO] ${N}대 SITL + 릴레이 정상 기동 완료"
echo ""
printf "  FastAPI 접속 포트: "
for j in $(seq 0 $((N-1))); do printf "%d " $((15760+j*10)); done
echo ""
printf "  공격 접속 포트  : "
for j in $(seq 0 $((N-1))); do printf "%d " $((25760+j*10)); done
echo ""
echo ""
echo "── 디버그 명령 (다른 터미널에서) ───────────────────────────────"
for j in $(seq 0 $((N-1))); do
    NUM=$((j+1))
    echo "  tail -f $LOG_DIR/arducopter_drone-0${NUM}.log"
    echo "  tail -f $LOG_DIR/mavproxy_drone-0${NUM}.log   # 릴레이 로그"
done
echo ""
echo "  ss -tlnp | grep -E '5760|5770|5780|15760|15770|15780'"
echo "  curl http://127.0.0.1:8000/api/debug | python3 -m json.tool"
echo ""
echo "  pkill -f arducopter ; pkill -f mavlink_tcp_relay ; pkill -f 'uvicorn app.main'   # 종료"
echo "================================================================"
echo "[INFO] FastAPI 서버 시작 (Ctrl+C로 전체 종료)"
echo ""

cd "$REPO_DIR"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
