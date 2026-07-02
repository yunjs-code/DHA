#!/bin/bash
# restart.sh — arducopter 직접 실행 (sim_vehicle.py/xterm 우회)
# ArduPilot SITL 포트 공식: SERIAL0 = 5760 + instance*10
#   drone-01 (-I0): TCP 5760   (5762, 5763도 내부 사용)
#   drone-02 (-I1): TCP 5770   (5772, 5773도 내부 사용)
#   drone-03 (-I2): TCP 5780   (5782, 5783도 내부 사용)

source "$HOME/venv-ardupilot/bin/activate"

ARDUCOPTER="$HOME/ardupilot/build/sitl/bin/arducopter"
HOME_POS="37.566535,126.977969,0.0,0.0"

# ── 1. 기존 프로세스 종료 ─────────────────────────────────────────────────────
echo "== [1] 기존 프로세스 종료 =="
pkill -f arducopter  2>/dev/null || true
pkill -f sim_vehicle 2>/dev/null || true
pkill -f mavproxy    2>/dev/null || true
pkill -f uvicorn     2>/dev/null || true
sleep 3

# ── 2. arducopter 직접 기동 (xterm 없이) ─────────────────────────────────────
echo "== [2] SITL 3대 직접 기동 =="
for i in 0 1 2; do
    PORT=$((5760+i*10))
    LOG="/tmp/sitl_drone-0$((i+1)).log"
    WDIR="/tmp/sitl_instance_$i"
    # 이전 파라미터 캐시(eeprom.bin) 삭제 — 인스턴스 간 파라미터 불일치 방지
    rm -rf "$WDIR"
    mkdir -p "$WDIR"
    echo "  drone-0$((i+1))  TCP:${PORT}  로그: ${LOG}"
    (cd "$WDIR" && "$ARDUCOPTER" \
        --model + \
        --speedup 2 \
        -I "$i" \
        --home "$HOME_POS" \
        --defaults /media/sf_uav/sitl_params.parm \
        > "$LOG" 2>&1 &)
    sleep 2
done

# ── 3. TCP 포트 대기 (최대 90초) ─────────────────────────────────────────────
echo "== [3] TCP 포트 열림 대기 =="
for i in 0 1 2; do
    PORT=$((5760+i*10))
    printf "  TCP:%-4d " $PORT
    READY=0
    for t in $(seq 1 45); do
        if (echo >/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then
            echo "열림 (약 $((t*2))초)"
            READY=1; break
        fi
        printf "."
        sleep 2
    done
    if [ $READY -eq 0 ]; then
        echo " !! 타임아웃 — 로그 확인: /tmp/sitl_drone-0$((i+1)).log"
    fi
done

# ── 4. FastAPI 서버 기동 ──────────────────────────────────────────────────────
echo ""
echo "== [4] FastAPI 서버 기동 =="
echo "   브라우저: http://192.168.56.101:8000/gcs/"
cd /media/sf_uav
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
