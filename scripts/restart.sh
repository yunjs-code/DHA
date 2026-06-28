#!/bin/bash
# restart.sh — Phase1: SITL(TCP) → Phase2: MAVProxy(UDP 릴레이) → Phase3: FastAPI
# SITL이 TCP 포트를 열 때까지 기다린 후 MAVProxy를 붙이므로 타이밍 실패 없음

source "$HOME/venv-ardupilot/bin/activate"

SIM_VEHICLE="$HOME/ardupilot/Tools/autotest/sim_vehicle.py"
N=3

# ── 1. 기존 프로세스 종료 ─────────────────────────────────────────────────────
echo "== [1] 기존 프로세스 종료 =="
pkill -f sim_vehicle 2>/dev/null || true
pkill -f arducopter  2>/dev/null || true
pkill -f mavproxy    2>/dev/null || true
pkill -f uvicorn     2>/dev/null || true
sleep 3

# ── 2. MAVProxy 설치 확인 ─────────────────────────────────────────────────────
echo "== [2] MAVProxy 확인 =="
if ! command -v mavproxy.py >/dev/null 2>&1; then
    echo "  MAVProxy 없음 → pip install mavproxy ..."
    pip install mavproxy -q
fi
echo "  $(mavproxy.py --version 2>&1 | head -1)"

# ── 3. SITL 기동 (--no-mavproxy: ArduCopter 단독, TCP 리슨) ──────────────────
echo "== [3] SITL ${N}대 기동 (TCP 모드) =="
for i in $(seq 0 $((N-1))); do
    TCP=$((5760+i))
    LOG="/tmp/sitl_drone-0$((i+1)).log"
    echo "  drone-0$((i+1))  TCP:${TCP}  로그: ${LOG}"
    python3 "$SIM_VEHICLE" \
        -v ArduCopter \
        -I "$i" \
        --speedup=1 \
        -L Seoul \
        --no-mavproxy \
        < /dev/null > "$LOG" 2>&1 &
    sleep 3
done

# ── 4. SITL TCP 포트가 열릴 때까지 폴링 (최대 90초) ─────────────────────────
echo "== [4] SITL TCP 포트 대기 =="
for i in $(seq 0 $((N-1))); do
    PORT=$((5760+i))
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

# ── 5. MAVProxy 시작 — TCP(SITL) → UDP(서버) 릴레이 ─────────────────────────
echo "== [5] MAVProxy UDP 릴레이 시작 =="
for i in $(seq 0 $((N-1))); do
    TCP=$((5760+i))
    UDP=$((14560+i*10))
    LOG="/tmp/mavproxy_drone-0$((i+1)).log"
    echo "  drone-0$((i+1))  TCP:${TCP} → UDP:${UDP}  로그: ${LOG}"
    mavproxy.py \
        --master "tcp:127.0.0.1:${TCP}" \
        --out "udpout:127.0.0.1:${UDP}" \
        --daemon \
        > "$LOG" 2>&1 &
    sleep 2
done

# ── 6. FastAPI 서버 기동 ──────────────────────────────────────────────────────
echo ""
echo "== [6] FastAPI 서버 기동 =="
echo "   브라우저: http://192.168.56.101:8000/gcs/"
echo "   MAVProxy → UDP 연결까지 수초 내 완료 예상"
cd /media/sf_uav
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
