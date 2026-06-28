# scripts/ — SITL 실행 스크립트 규칙

## 파일
| 파일 | 역할 |
|------|------|
| `start_sitl.sh` | ArduPilot SITL N대 실행 |

---

## start_sitl.sh 설계

### 역할
ArduCopter SITL 인스턴스를 지정한 수만큼 실행.
각 인스턴스는 UDP로 텔레메트리를 서버로 전송.

### 실행 방식
```bash
# 기본 (3대)
bash scripts/start_sitl.sh

# 대수 지정
bash scripts/start_sitl.sh 2
```

### 드론별 포트 매핑
| 드론 | SITL 인스턴스 | UDP out 포트 |
|------|--------------|-------------|
| drone-01 | -I 0 | 14560 |
| drone-02 | -I 1 | 14570 |
| drone-03 | -I 2 | 14580 |

### sim_vehicle.py 호출 형식
```bash
sim_vehicle.py -v ArduCopter -I ${i} \
    --out=udpout:127.0.0.1:$((14560 + i*10)) \
    --no-mavproxy \
    --speedup=1 \
    -L Seoul \
    &
```

### 위치 정의 (`-L Seoul`)
ArduPilot 위치 파일에 Seoul 추가 필요 (37.5665, 126.9780, 0, 0).
경로: `~/ardupilot/Tools/autotest/locations.txt`

---

## 규칙
- 스크립트는 `/media/sf_uav` (VirtualBox 공유폴더) 에서 실행
- `sim_vehicle.py` 경로: `~/ardupilot/Tools/autotest/sim_vehicle.py`
- 각 인스턴스는 백그라운드(`&`)로 실행
- 종료: `pkill -f sim_vehicle` 또는 `pkill -f arducopter`
- 포트 충돌 확인: `ss -ulnp | grep 1456`
- 로그는 `/tmp/sitl_drone-0N.log`에 저장

## Linux VM 전제 조건
- ArduPilot 빌드 완료: `~/ardupilot/build/sitl/bin/arducopter` 존재
- Python 환경: `source ~/venv-ardupilot/bin/activate`
- 공유폴더 마운트: `/media/sf_uav`
