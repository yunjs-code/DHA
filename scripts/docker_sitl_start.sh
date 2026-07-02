#!/bin/bash
# Docker 컨테이너 안에서 ArduCopter SITL 3대 실행
# 포트: drone-01=5760, drone-02=5770, drone-03=5780

ARDUCOPTER="$HOME/ardupilot/build/sitl/bin/arducopter"
HOME_POS="37.566535,126.977969,0.0,0.0"
PARAMS="$HOME/sitl_params.parm"

echo "=== UAV Security Testbed — SITL 3대 시작 ==="

for i in 0 1 2; do
    PORT=$((5760 + i * 10))
    WDIR="/tmp/sitl_instance_$i"
    LOG="/tmp/sitl_drone-0$((i+1)).log"
    mkdir -p "$WDIR"
    echo "  drone-0$((i+1)) → TCP:$PORT  로그: $LOG"
    (cd "$WDIR" && "$ARDUCOPTER" \
        --model + \
        --speedup 2 \
        -I "$i" \
        --home "$HOME_POS" \
        --defaults "$PARAMS" \
        > "$LOG" 2>&1) &
    sleep 3
done

echo ""
echo "  drone-01: TCP:5760"
echo "  drone-02: TCP:5770"
echo "  drone-03: TCP:5780"
echo ""
echo "로그 확인: docker exec <container> cat /tmp/sitl_drone-01.log"

wait
