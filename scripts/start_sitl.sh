#!/bin/bash
# ArduCopter SITL N대 실행 (MAVProxy UDP 릴레이)
# 사용법: bash scripts/start_sitl.sh [대수=3]

set -e

N=${1:-3}
ARDUPILOT_DIR="$HOME/ardupilot"
SIM_VEHICLE="$ARDUPILOT_DIR/Tools/autotest/sim_vehicle.py"
LOG_DIR="/tmp"

if [ ! -f "$SIM_VEHICLE" ]; then
    echo "[ERROR] sim_vehicle.py 없음: $SIM_VEHICLE"
    exit 1
fi

source "$HOME/venv-ardupilot/bin/activate"

echo "[INFO] SITL ${N}대 시작..."

for i in $(seq 0 $((N - 1))); do
    DRONE_NUM=$((i + 1))
    UDP_PORT=$((14560 + i * 10))
    LOG="$LOG_DIR/sitl_drone-0${DRONE_NUM}.log"

    echo "[INFO] drone-0${DRONE_NUM} 시작 (UDP out → 127.0.0.1:${UDP_PORT})"

    python3 "$SIM_VEHICLE" \
        -v ArduCopter \
        -I "$i" \
        --speedup=1 \
        -L Seoul \
        --out "udpout:127.0.0.1:${UDP_PORT}" \
        < /dev/null \
        > "$LOG" 2>&1 &

    echo "[INFO] drone-0${DRONE_NUM} PID=$! 로그: $LOG"
    sleep 5
done

echo ""
echo "[INFO] 전체 ${N}대 백그라운드 실행 완료"
echo "[INFO] UDP 포트: $(for j in $(seq 0 $((N-1))); do echo -n "$((14560 + j * 10)) "; done)"
echo "[INFO] 종료: pkill -f sim_vehicle"
echo "[INFO] 약 60초 후 MAVProxy가 ArduCopter에 연결되어 UDP 전송 시작"
