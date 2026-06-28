# UAV Security Testbed — 프로젝트 규칙

## 목표 (3가지만)
1. 실제 전장 지휘소·드론 통신 구조를 그대로 재현
2. 공격자 화면: 실제로 오가는 MAVLink 바이너리 패킷 표시
3. GCS 화면: 명령 전송 UI + 드론 위치 지도

## ★ 절대 규칙 — 어떤 이유로도 어기지 않는다

### R1. 서버 ↔ SITL 구간은 MAVLink v2 바이너리만 허용
- JSON 직렬화, REST 호출, 문자열 명령 전달 금지
- pymavlink recv → 파싱 → WebSocket JSON 순서만 허용
- SITL로 보내는 명령: 반드시 COMMAND_LONG 바이너리로 인코딩

### R2. 금지 기능 목록 — 추가하지 않는다
- AI/ML 탐지 (IsolationForest, RuleEngine 등)
- 공격 주입 시뮬레이터 (AttackManager, injector)
- MQTT 브로커 연동
- SATCOM/위성 채널 에뮬레이션
- RTSP 영상 스트림
- 시나리오 엔진
- 시뮬레이션 전용 내부 필드 (`_ground_truth`, `malformed`)

### R3. 브라우저 ↔ 서버는 WebSocket JSON만 허용
- GCS: 드론 위치·상태를 JSON으로 수신, 명령을 JSON으로 송신
- Attacker: MAVLink 패킷을 hex + 파싱 결과 JSON으로 수신
- REST API는 서버 상태 조회용 최소한만 허용

## 실제 전장 vs 우리 구조
```
실제: [QGC] ── MAVLink binary ──→ [SiK 915MHz] ──→ [드론 FC]
우리: [브라우저] ── WS JSON ──→ [서버] ── MAVLink binary ──→ [SITL]
                                          ↑ R1이 지키는 구간
```

## 파일 구조
```
app/          ← 각 파일별 CLAUDE.md 참고
frontend/gcs/      ← frontend/gcs/CLAUDE.md 참고
frontend/attacker/ ← frontend/attacker/CLAUDE.md 참고
scripts/      ← SITL 실행 스크립트
CLAUDE.md     ← 이 파일 (프로젝트 전체 규칙)
```

## 포트
| 용도 | 포트 | 프로토콜 |
|------|------|---------|
| FastAPI HTTP/WS | 8000 | TCP |
| SITL drone-01 | 5760 | TCP (서버가 접속) |
| SITL drone-02 | 5761 | TCP (서버가 접속) |
| SITL drone-03 | 5762 | TCP (서버가 접속) |

## 스택
- 백엔드: Python 3.11 + FastAPI + pymavlink
- 프론트엔드: Vanilla JS + Leaflet.js (빌드 도구 없음)
- SITL: ArduPilot ArduCopter (실제 FC 펌웨어)
- 의존성: `requirements.txt` 기준, 새 패키지 추가 시 반드시 기재

## 개발 로드맵

### 머신 역할
| 머신 | IP | 하는 일 |
|------|----|---------|
| Windows 호스트 | 192.168.56.1 | 코드 작성 (Claude/VS Code), 브라우저로 화면 확인 |
| Linux VM (drone-server) | 192.168.56.101 | SITL 실행, FastAPI 서버 실행 |

### 코드 흐름
```
Windows에서 코드 작성·저장
    ↓ VirtualBox 공유폴더 (자동 동기화, 별도 전송 없음)
VM /media/sf_uav/ 에 즉시 반영
    ↓ uvicorn --reload 가 변경 감지 후 자동 재시작
Windows 브라우저에서 http://192.168.56.101:8000 접속해서 확인
```

### 구현 순서 (PLAN.md 참고)
```
Phase 1: app/mavlink.py   ← MAVLink 바이너리 인코딩·디코딩
Phase 2: app/sitl.py      ← pymavlink UDP 수신·송신
Phase 3: app/main.py      ← FastAPI WebSocket 허브
Phase 4: frontend/gcs/    ← 지도 + 명령 UI
Phase 5: frontend/attacker/ ← 패킷 스트림 뷰어
```

### VM 서버 실행 명령 (매 세션)
```bash
source ~/venv-ardupilot/bin/activate
cd /media/sf_uav
bash scripts/start_sitl.sh          # SITL 3대 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
