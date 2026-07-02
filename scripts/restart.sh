#!/bin/bash
# restart.sh — arducopter 직접 실행 + MAVProxy 릴레이 (다중 클라이언트 허용)
#
# 포트 구조:
#   ArduCopter SITL (단일 연결): 5760 / 5770 / 5780  ← MAVProxy 전용
#   MAVProxy 릴레이 (다중 연결): 15760 / 15770 / 15780 ← FastAPI + inject_attack.py

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

# ── 2. arducopter 직접 기동 ──────────────────────────────────────────────────
echo "== [2] SITL 3대 직접 기동 =="
for i in 0 1 2; do
    PORT=$((5760+i*10))
    LOG="/tmp/sitl_drone-0$((i+1)).log"
    WDIR="/tmp/sitl_instance_$i"
    rm -rf "$WDIR" && mkdir -p "$WDIR"
    echo "  drone-0$((i+1))  SITL TCP:${PORT}  로그: ${LOG}"
    (cd "$WDIR" && "$ARDUCOPTER" \
        --model + \
        --speedup 2 \
        -I "$i" \
        --home "$HOME_POS" \
        --defaults /media/sf_uav/sitl_params.parm \
        > "$LOG" 2>&1 &)
    sleep 2
done

# ── 3. SITL TCP 포트 대기 ────────────────────────────────────────────────────
echo "== [3] SITL TCP 포트 열림 대기 =="
for i in 0 1 2; do
    PORT=$((5760+i*10))
    printf "  SITL TCP:%-4d " $PORT
    READY=0
    for t in $(seq 1 45); do
        if (echo >/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then
            echo "열림 (약 $((t*2))초)"
            READY=1; break
        fi
        printf "."
        sleep 2
    done
    [ $READY -eq 0 ] && echo " !! 타임아웃 — 로그: /tmp/sitl_drone-0$((i+1)).log"
done

# ── 4. MAVProxy 릴레이 기동 (SITL 1개 연결 → FastAPI용·공격자용 포트 분리) ───
#   FastAPI  → tcpin:15760/15770/15780  (클라이언트 1개 전용)
#   attacker → tcpin:25760/25770/25780  (클라이언트 1개 전용)
#   tcpin은 포트당 동시 클라이언트 1개만 처리하므로 포트를 분리한다.
echo ""
echo "== [4] MAVProxy 릴레이 기동 =="
for i in 0 1 2; do
    SITL_PORT=$((5760+i*10))
    RELAY_PORT=$((15760+i*10))
    ATCK_PORT=$((25760+i*10))
    LOG="/tmp/mavproxy_drone-0$((i+1)).log"
    echo "  drone-0$((i+1))  SITL:${SITL_PORT} → FastAPI:${RELAY_PORT}  Attack:${ATCK_PORT}"
    mavproxy.py \
        --master "tcp:127.0.0.1:${SITL_PORT}" \
        --out "tcpin:0.0.0.0:${RELAY_PORT}" \
        --out "tcpin:0.0.0.0:${ATCK_PORT}" \
        --daemon \
        --logfile "$LOG" \
        > /dev/null 2>&1 &
    sleep 3
done

# ── 5. 릴레이 포트 대기 ──────────────────────────────────────────────────────
echo ""
echo "== [5] 릴레이 포트 열림 대기 =="
for i in 0 1 2; do
    RELAY_PORT=$((15760+i*10))
    ATCK_PORT=$((25760+i*10))
    printf "  FastAPI TCP:%-5d " $RELAY_PORT
    for t in $(seq 1 20); do
        if (echo >/dev/tcp/127.0.0.1/$RELAY_PORT) 2>/dev/null; then
            echo "열림"; break
        fi
        printf "."; sleep 1
    done
    echo ""
    printf "  Attack  TCP:%-5d " $ATCK_PORT
    for t in $(seq 1 20); do
        if (echo >/dev/tcp/127.0.0.1/$ATCK_PORT) 2>/dev/null; then
            echo "열림"; break
        fi
        printf "."; sleep 1
    done
    echo ""
done

# ── 6. FastAPI 서버 기동 ──────────────────────────────────────────────────────
echo ""
echo "== [6] FastAPI 서버 기동 =="
echo "   GCS:      http://192.168.56.101:8000/gcs/"
echo "   Attacker: http://192.168.56.101:8000/attacker/"
echo "   FastAPI  포트: 15760 / 15770 / 15780"
echo "   Attacker 포트: 25760 / 25770 / 25780  ← inject_attack.py 전용"
cd /media/sf_uav
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
