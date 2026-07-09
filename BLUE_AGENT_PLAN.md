# Blue Defense Agent 구현 계획

> 이 파일은 Blue Agent 개발의 단일 진행 관리 문서다.
> **작업을 시작하기 전에 이 파일을 먼저 읽고, 어떤 Phase/작업인지 확인한 뒤 진행한다.**
> 작업 하나를 완료하면 해당 체크박스를 `[ ]` → `[x]`로 바꾸고, 바로 아래 "완료 로그"에 날짜와 변경 파일을 한 줄 추가한다.
> 코드는 절대 한 번에 몰아서 작성하지 않는다 — Phase 단위, 그 안에서도 작업(task) 단위로 작게 구현하고 매번 결과를 보고한다.

## 접근 경로 / 라우팅 확정 사항

- 대시보드 URL: `http://192.168.56.101:8000/blue_agent` (정적 마운트, 기존 `/gcs`, `/attacker`와 동일한 패턴)
- WebSocket: `/ws/blue_agent` (신규 `blue_mgr`, 기존 `gcs_mgr`/`att_mgr`와 동일한 `_WsManager` 재사용)
- 기존 `/gcs`, `/attacker`, `/api/*`, `/ws/gcs`, `/ws/attacker`는 **절대 변경하지 않는다** (CLAUDE.md R1/R3 및 기존 스펙 유지).

## 대시보드 요구사항 (사용자 확정)

1. **지도**: GCS와 동일하게 Leaflet 기반 드론 위치 표시 (telemetry는 기존 `_broadcast_loop()`가 만드는 데이터를 재사용 — 새로 계산하지 않음).
2. **공격 탐지 UI**: 현재 공격 판정(Current Attack), 타임라인, 위험도 점수(Risk Score), 드론 상태, 활성 룰 목록, MITRE 매핑.
3. **방어 조치 UI**: 자동 대응(Risk Level에 따른 자동 Log/Alert/Drop/Block)뿐 아니라, **운영자가 직접 버튼으로 방어 조치를 발동**할 수 있어야 한다 (예: 특정 드론 강제 RTL, 명령 차단 ON/OFF, 연결 차단). 즉 Response Engine은 자동 트리거 경로 + 수동(오퍼레이터) 트리거 경로 둘 다 지원한다.

## 파이프라인

```
MAVLink Packet (_broadcast_loop) ─┐
AttackRunner.emit() (attack meta) ─┼─▶ EventEngine ─▶ RuleEngine ─▶ RiskEngine ─▶ AIThreatAnalyzer
                                    │                                     │
                                    │                                     ▼
                                    │                            ResponseEngine (자동)
                                    │                                     ▲
                                    │                      오퍼레이터 수동 명령 (/ws/blue_agent)
                                    ▼
                        blue_mgr broadcast (지도용 telemetry + 탐지/위험도/MITRE)
```

---

## Phase 0 — 기반 준비

- [x] `requirements.txt`: `openai>=1.0.0` 추가 (Claude용 자리 주석 포함)
- [x] `app/mavlink.py`: `decode()`의 `base` dict에 `seq`(raw[4]), `incompat_flags`(raw[2]), `signed`(`bool(incompat_flags & 0x01)`) 필드 추가 (기존 필드는 유지, 추가만)
- [x] `app/blue_agent/__init__.py`, `app/blue_agent/config.py` — 설정 로더 골격 (임계값/가중치는 Phase 3에서 채움)
- [x] `app/blue_agent/models/events.py` — `SecurityEvent` 베이스 dataclass + 하위 이벤트(`HeartbeatEvent`, `CommandEvent`, `GPSInjectionEvent`, `TelemetryEvent`, `RawPacketEvent`)

### 완료 로그
- 2026-07-08: requirements.txt — `openai>=1.0.0` 추가 (Blue Agent AI Threat Analyzer 기본 구현체용, Claude provider 자리는 주석으로 표시)
- 2026-07-08: app/mavlink.py — `decode()` base dict에 `seq`/`incompat_flags`/`signed` 필드 추가 (기존 필드 유지, 서명 여부 판별 가능해짐)
- 2026-07-08: app/blue_agent/__init__.py, app/blue_agent/config.py — 패키지 골격 및 `BlueAgentConfig`/`load_config()` 설정 로더 스켈레톤 생성 (가중치·임계값은 Phase 3에서 채움)
- 2026-07-08: app/blue_agent/models/__init__.py, app/blue_agent/models/events.py — `SecurityEvent` 베이스 + `HeartbeatEvent`/`CommandEvent`/`GPSInjectionEvent`/`TelemetryEvent`/`RawPacketEvent` dataclass 생성 (mavlink.decode() 출력과 attacks.py emit() evidence 필드를 반영)

---

## Phase 1 — Event Engine (완료)

- [x] `app/blue_agent/event/engine.py` — raw MAVLink dict / attack 메타 → `SecurityEvent` 변환
- [x] `app/main.py`: `_broadcast_loop()`의 `drain_raw()` 처리 직후 `EventEngine.ingest()` 훅 1줄 추가
- [x] `app/main.py`: `_broadcast_loop()`의 telemetry 브로드캐스트 지점에 `blue_mgr.broadcast(telemetry)` 추가 (대시보드 지도용, 기존 gcs/attacker 브로드캐스트는 그대로 둠)
- [x] `app/attacks.py`: `AttackRunner.emit()` 호출부에 `EventEngine.ingest()` 보완 훅 추가 (원본 공격 패킷이 SITLConnector 쪽에서 안 보이는 유니캐스트 한계 보완)
- [x] `tests/blue_agent/test_event_engine.py`

### 완료 로그
- 2026-07-08: app/blue_agent/event/__init__.py, app/blue_agent/event/engine.py — `EventEngine` 생성. `ingest_packet()`은 mav.decode() 결과(msg_name 기준)를 HeartbeatEvent/CommandEvent/TelemetryEvent/RawPacketEvent로 변환하고, `ingest_attack()`은 attack_id 접두어(`att02_`=GPS 스푸핑 → GPSInjectionEvent, 그 외=CommandEvent)로 attacks.py emit() 메타를 변환. attack_id가 `att0N_<drone_id>` 형식임을 main.py의 `/api/attack/start` id_map에서 확인해 접두어 매칭으로 구현
- 2026-07-08: app/main.py — import 1줄(`event_engine`) + `_broadcast_loop()`의 `drain_raw()`/`mav.decode()` 처리 직후 `event_engine.ingest_packet(drone_id, parsed)` 훅 1줄 추가. 기존 att_mgr 브로드캐스트 로직은 그대로 유지 (R1/R3 위반 없음, py_compile로 문법 확인)
- 2026-07-08: app/main.py — `blue_mgr = _WsManager()` 인스턴스 추가(기존 gcs_mgr/att_mgr와 동일 패턴) + telemetry 브로드캐스트 지점(`await gcs_mgr.broadcast(tele_msg)` / `await att_mgr.broadcast(tele_msg)` 바로 뒤)에 `await blue_mgr.broadcast(tele_msg)` 1줄 추가. 기존 gcs/attacker 브로드캐스트는 순서·내용 변경 없음. `/ws/blue_agent` 엔드포인트는 Phase 7에서 추가 예정이라 현재는 구독자 없이 대기 상태(py_compile로 문법 확인)
- 2026-07-08: app/attacks.py — import 1줄(`event_engine`) + `AttackRunner.emit()` 본문 첫 줄에 `event_engine.ingest_attack(drone_id, attack_id, evidence or {})` 훅 1줄 추가. `emit()`은 att01/att02/att03 세 공격 코루틴이 공통으로 호출하는 지점이라 훅 하나로 세 공격 모두 커버됨. circular import 없음(`event.engine`은 `attacks.py`를 참조하지 않음) — `python -c "import app.attacks"` 정상 확인
- 2026-07-08: tests/__init__.py, tests/blue_agent/__init__.py, tests/blue_agent/test_event_engine.py — `EventEngine.ingest_packet()`(HEARTBEAT/COMMAND_LONG/COMMAND_ACK/GLOBAL_POSITION_INT/VFR_HUD/미지원 msg→RawPacketEvent fallback 6종)와 `ingest_attack()`(att01/att02/att03 접두어 3종) 총 9개 케이스 검증. pytest가 requirements.txt에 없어 표준 라이브러리 `unittest`로 작성 — 신규 의존성 추가 없음. `python -m unittest tests.blue_agent.test_event_engine -v` 9개 전부 OK

**Phase 1 완료.** 다음 Phase(2 — Rule Engine) 시작 전 사용자 확인 대기.

---

## Phase 2 — Rule Engine (플러그인 자동 등록)

- [x] `app/blue_agent/rules/base.py` — `BaseRule` ABC
- [x] `app/blue_agent/rules/__init__.py` — `pkgutil` 기반 자동 스캔·등록
- [x] `rules/sysid_spoofing.py`
- [x] `rules/duplicate_sysid.py`
- [x] `rules/unsigned_packet.py`
- [x] `rules/flight_termination.py`
- [x] `rules/command_flood.py`
- [x] `rules/gps_injection.py`
- [x] `rules/packet_replay.py`
- [x] `rules/sequence_anomaly.py`
- [x] `rules/unknown_mode_change.py`
- [x] `rules/rtl_abuse.py`
- [x] `tests/blue_agent/test_rules.py`

### 완료 로그
- 2026-07-08: app/blue_agent/rules/base.py — `RuleResult`(rule_id, drone_id, severity, message, evidence, ts) dataclass + `BaseRule` ABC(`evaluate(event) -> RuleResult | None`) 신규 작성. `rule_id`는 `config.py`의 `BlueAgentConfig.rule_weights` 딕셔너리 키와 짝을 맞추도록 설계 (Phase 3에서 룰별 가중치 매핑에 그대로 사용). 룰이 드론별 상태(이전 seq, 최근 발생 시각 등)를 들고 있어야 하는 경우가 많아 룰은 매 이벤트마다 새로 만들지 않고 인스턴스를 재사용하는 구조로 설계 — `python -c "from app.blue_agent.rules.base import BaseRule, RuleResult"` 정상 확인
- 2026-07-08: app/blue_agent/rules/__init__.py — `pkgutil.iter_modules`로 `rules/` 디렉터리의 서브모듈(자기 자신 `base` 제외)을 전부 import한 뒤 `BaseRule.__subclasses__()`로 구현체를 모아 `ALL_RULES` 리스트 생성. 새 룰 파일 추가 시 `BaseRule`만 상속하면 등록 코드 수정 없이 자동 포함됨 — `python -c "from app.blue_agent.rules import ALL_RULES; print(ALL_RULES)"` → `[]` (룰 파일 아직 없어 정상)
- 2026-07-08: app/blue_agent/rules/sysid_spoofing.py — `SysidSpoofingRule` 신규 작성. 정상 트래픽엔 드론 FC sysid(최초 HEARTBEAT에서 학습)와 GCS sysid(255, sitl.py의 `source_system=255` 고정 전송) 두 개만 존재해야 한다는 전제로, HeartbeatEvent/CommandEvent/RawPacketEvent 중 이 두 값 밖의 sysid가 나오면 HIGH 등급 탐지. sysid<=0(공격 evidence 기반 합성 이벤트의 기본값)은 오탐 방지를 위해 제외 — `python -c "from app.blue_agent.rules import ALL_RULES; print(ALL_RULES)"` → `[SysidSpoofingRule 인스턴스 1개]` 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/duplicate_sysid.py — `DuplicateSysidRule` 신규 작성. HeartbeatEvent 기준으로 sysid→최초 관측 drone_id 매핑을 유지하다가, 이미 다른 drone_id가 점유한 sysid를 자처하는 HEARTBEAT가 다른 drone_id 채널에서 나타나면 HIGH 등급 탐지(서로 다른 SITL 연결이 동일 시스템 ID를 자처 = 사칭 의심). sysid_spoofing과 달리 단일 채널이 아닌 drone_id 간 교차 검증 — `ALL_RULES` → `['duplicate_sysid', 'sysid_spoofing']` 2개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/unsigned_packet.py — `UnsignedPacketRule` 신규 작성. 서명(§3.3 defense_signing.py)은 선택적으로 켜지므로 무서명 패킷 자체를 무조건 탐지하면 오탐 폭증 — 대신 CommandEvent/RawPacketEvent에서 drone_id별로 `signed=True` 관측 이력을 학습해두고, 이후 같은 채널에서 무서명 패킷이 나타나면 서명 우회/다운그레이드 의심으로 HIGH 등급 탐지. sysid 룰들과 동일한 "베이스라인 학습 후 이탈 탐지" 패턴 적용 — `ALL_RULES` → `['duplicate_sysid', 'sysid_spoofing', 'unsigned_packet']` 3개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/flight_termination.py — `FlightTerminationRule` 신규 작성. 이 시스템의 정상 GCS UI(POST /api/command)는 ARM/DISARM/TAKEOFF/LAND/RTL/GOTO/SET_MODE만 노출하므로 MAV_CMD_DO_FLIGHTTERMINATION(185)이 담긴 CommandEvent는 baseline 학습 없이도 그 자체로 비정상 — 앞선 3개 룰과 달리 "베이스라인 학습 후 이탈" 패턴이 아닌 즉시 판정 방식이며, 성공 시 드론이 즉시 추락하는 가장 파괴적인 명령이라 처음으로 CRITICAL 등급 사용 — `ALL_RULES` → `['duplicate_sysid', 'flight_termination', 'sysid_spoofing', 'unsigned_packet']` 4개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/command_flood.py — `CommandFloodRule` 신규 작성. drone_id별로 CommandEvent 발생 시각을 deque에 쌓아 2초 슬라이딩 윈도우를 유지하다가 윈도우 내 건수가 5건을 초과하면 명령 플러딩(자동화 주입/DoS 성격) 의심으로 탐지. 정상 GCS 조작은 사용자가 버튼을 누를 때만 발생해 초당 여러 건이 나오지 않는다는 전제 — 파괴적 단일 명령(flight_termination)보다는 낮은 등급으로 처음 MEDIUM 사용 — `ALL_RULES` → `['command_flood', 'duplicate_sysid', 'flight_termination', 'sysid_spoofing', 'unsigned_packet']` 5개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/gps_injection.py — `GpsInjectionRule` 신규 작성. GPSInjectionEvent는 engine.py의 `ingest_attack()`이 att02_(GNSS 스푸핑) attack_id일 때만 생성하는 공격 스크립트발 합성 이벤트라, 발생 자체는 이미 공격 신호이지만 offset_m이 미미한 초기 단계까지 전부 올리면 노이즈가 커서 OFFSET_THRESHOLD_M(5.0m) 이상 드리프트 또는 드론 자체 EKF가 이미 이상을 감지한 경우(ekf_alarm=True)만 탐지하도록 제한. 다른 룰들과 달리 실시간 MAVLink 패킷이 아닌 공격 시뮬레이션 계측값을 입력으로 사용하는 첫 룰 — EKF 알람까지 뜬 경우는 항법 안전장치가 이미 반응한 상태라 CRITICAL로 격상, 그 외는 HIGH — `ALL_RULES` → `['command_flood', 'duplicate_sysid', 'flight_termination', 'gps_injection', 'sysid_spoofing', 'unsigned_packet']` 6개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/packet_replay.py — `PacketReplayRule` 신규 작성. MAVLink seq는 발신 sysid마다 0~255를 순환하는 8비트 카운터라 256개 패킷마다 자연스럽게 같은 값이 재출현하므로, drone_id+sysid 단위로 최근 WINDOW(250)개 seq 이력을 deque로 유지하다가 이 윈도우 안에서 동일 seq가 다시 나타나면(자연 순환보다 훨씬 이른 재출현) 캡처한 패킷을 그대로 재주입하는 replay 공격으로 HIGH 등급 탐지 — HeartbeatEvent/CommandEvent/RawPacketEvent 공통으로 sysid+seq 필드를 갖는 점을 이용 — `ALL_RULES` → `['command_flood', 'duplicate_sysid', 'flight_termination', 'gps_injection', 'packet_replay', 'sysid_spoofing', 'unsigned_packet']` 7개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/sequence_anomaly.py — `SequenceAnomalyRule` 신규 작성. drone_id+sysid 단위로 직전 seq만 기억해두고 매 이벤트마다 `(seq - last_seq) % 256` 진행폭을 계산 — 정상 유실 허용치 GAP_MAX(20)를 초과하면 MEDIUM 등급 탐지. mod 256 연산 특성상 큰 전진(대량 패킷 유실/세션 재시작)과 사실상의 후진(같은 sysid를 사칭하며 다른 발신원이 끼어들어 seq가 거꾸로 감)이 모두 "허용치를 넘는 큰 진행폭"으로 동일하게 잡히므로 하나의 임계치로 함께 커버. sysid_spoofing/duplicate_sysid는 sysid 자체가 바뀌거나 충돌할 때만 탐지하는데, 공격자가 sysid를 그대로 사칭하며 패킷을 끼워 넣는 경우는 이 룰이 보완 — `ALL_RULES` → `['command_flood', 'duplicate_sysid', 'flight_termination', 'gps_injection', 'packet_replay', 'sequence_anomaly', 'sysid_spoofing', 'unsigned_packet']` 8개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/unknown_mode_change.py — `UnknownModeChangeRule` 신규 작성. CLAUDE.md에 문서화된 이 테스트베드의 정상 운용 모드(STABILIZE/AUTO/GUIDED/LOITER/RTL/LAND) 화이트리스트를 두고, drone_id별로 직전 HeartbeatEvent.mode를 기억하다가 값이 "바뀌었는데" 새 값이 화이트리스트 밖이면 HIGH 등급 탐지 — 매 하트비트(수 Hz)마다 반복 경보되지 않도록 실제 전환 시점에만 판정. SET_MODE는 COMMAND_LONG이 아닌 네이티브 `set_mode_send()`로 전송되어 CommandEvent로 잡히지 않으므로(quirk), HeartbeatEvent.mode 변화가 비인가 모드 전환을 볼 수 있는 유일한 관측 신호 — `ALL_RULES` → `['command_flood', 'duplicate_sysid', 'flight_termination', 'gps_injection', 'packet_replay', 'sequence_anomaly', 'sysid_spoofing', 'unknown_mode_change', 'unsigned_packet']` 9개 자동 등록 확인
- 2026-07-08: app/blue_agent/rules/rtl_abuse.py — `RtlAbuseRule` 신규 작성. 이 코드베이스에서 RTL로 전환하는 경로(GCS UI의 app/sitl.py, att01_ 공격 스크립트의 app/attacks.py 모두)는 예외 없이 네이티브 `set_mode_send`/`set_mode_encode`만 사용하며 COMMAND_LONG으로 MAV_CMD_NAV_RETURN_TO_LAUNCH(20)를 보내는 코드는 어디에도 없음(app/sitl.py의 `20: "RTL"`은 관측용 이름 매핑일 뿐 발신 경로 아님) — 이를 grep+Read로 직접 확인 후, flight_termination.py와 동일하게 baseline 학습 없이 CommandEvent.command==20 관측 즉시 HIGH 등급으로 판정하도록 설계. unknown_mode_change(HeartbeatEvent.mode 기반)와 달리 COMMAND_LONG 채널 자체의 오남용을 잡는 상호보완 룰 — `ALL_RULES` → `['command_flood', 'duplicate_sysid', 'flight_termination', 'gps_injection', 'packet_replay', 'rtl_abuse', 'sequence_anomaly', 'sysid_spoofing', 'unknown_mode_change', 'unsigned_packet']` 10개 자동 등록 확인
- 2026-07-08: tests/blue_agent/test_rules.py — 10종 룰 전체에 대한 단위 테스트 30개 신규 작성. `ALL_RULES` 싱글턴 대신 각 테스트마다 Rule 클래스를 새로 인스턴스화해 baseline 학습형(sysid_spoofing/duplicate_sysid/unsigned_packet/unknown_mode_change)·윈도우형(command_flood/packet_replay/sequence_anomaly) 룰의 인스턴스 상태가 테스트 간 오염되지 않도록 설계. 임계값 경계(command_flood 5→6건, sequence_anomaly GAP_MAX=20 안/밖, gps_injection offset+ekf_alarm 조합), seq mod-256 순환·역전, packet_replay의 deque(maxlen=250) 실제 eviction(251개 삽입 후 evict된 seq 재조회 시 미탐지 확인) 등 경계조건까지 함께 검증 — `python -m unittest tests.blue_agent.test_rules -v` → "Ran 30 tests in 0.002s / OK" 전건 통과 확인
- 2026-07-08 (버그 수정): app/blue_agent/rules/packet_replay.py, tests/blue_agent/test_rules.py — 실사용 중 공격을 하지 않았는데도 모든 드론이 EMERGENCY로 즉시 차단되는 오탐 발견(로그에 `score=6986.0`부터 `+7.0`씩 증가하는 EMERGENCY가 같은 초에 연속 발생, HIGH severity 7.0×weight 1.0과 정확히 일치해 packet_replay가 원인임을 특정). 원인은 seq 재출현 판단 기준이 "최근 250개 이력 안에 있는가"였는데, MAVLink seq는 sysid당 0~255를 도는 8비트 카운터를 모든 메시지 타입이 공유하고 SITL의 `MAV_DATA_STREAM_ALL` 10Hz 요청이 여러 스트림 그룹으로 팬아웃되어 합산 메시지율이 훨씬 높아, 정상 트래픽에서도 seq가 1~3초 만에 자연스럽게 한 바퀴 돌아 재출현 — 이걸 전부 재전송(replay) 공격으로 오판했다. 개수 기반 이력을 `(seq, timestamp)` 쌍으로 바꾸고 `REPLAY_WINDOW_SECONDS=0.4`초보다 오래된 항목은 검사 전에 제거하도록 수정해 "너무 이른 재출현"만 탐지(개수 상한 500은 메모리 안전장치로만 유지). 기존 count-based eviction 테스트를 `unittest.mock.patch`로 시간을 고정한 테스트 2건(윈도우 만료 후 재출현 시 미탐지, 윈도우 내 고빈도 트래픽에서도 진짜 재출현은 여전히 탐지)으로 교체 — `python -m unittest tests.blue_agent.test_rules -v` 31/31 통과, 전체 스위트 71/72 통과(나머지 1건은 Windows 호스트에 fastapi 미설치로 인한 test_main.py 환경 문제로 이 수정과 무관) 확인
- 2026-07-08 (버그 수정): app/blue_agent/rules/duplicate_sysid.py, scripts/start_sitl.sh, tests/blue_agent/test_rules.py — GCS 페이지에서 보내는 모든 명령이 계속 EMERGENCY로 차단된다는 사용자 신고. 원인은 두 가지가 겹친 것: (1) `scripts/start_sitl.sh`가 SITL 3대를 띄울 때 `SYSID_THISMAV`를 지정하지 않아 인스턴스별 `-I` 값(포트 오프셋일 뿐 MAVLink sysid가 아님)과 무관하게 전부 기본값 sysid=1로 부팅되어, drone-02/03의 HEARTBEAT가 drone-01과 동일 sysid를 자처 — duplicate_sysid 룰이 이를 지속적인 sysid 사칭으로 판정. (2) `duplicate_sysid.py`가 (sysid, drone_id) 충돌이 확정된 이후에도 매 HEARTBEAT(~1Hz)마다 HIGH를 반복 반환해, 30초 슬라이딩 윈도우 누적 점수가 EMERGENCY 임계값을 한참 초과 — unsigned_packet.py에서 이미 한 차례 고친 것과 동일한 "누적 상태 vs 전환 상태" 패턴의 버그. 수정은 두 부분: `start_sitl.sh`가 인스턴스별 `$WORK_DIR/default_params.parm`에 `SYSID_THISMAV ${DRONE_NUM}`을 써서 `--wipe --defaults "$DEFAULTS_FILE"`로 부팅해 각 드론이 고유 sysid를 갖도록 근본 원인 제거, `duplicate_sysid.py`는 `_was_duplicate: dict[str, bool]`로 drone_id별 직전 충돌 여부를 기억해 "이 채널이 처음 충돌 상태에 진입하는 전환 시점"에만 채점하도록 변경(계속되는 동일 충돌은 재채점하지 않음). `app/attacks.py`의 `AttackRunner.emit()` 공격 주입 경로는 별도 MAVLink 연결(`ATTACK_PORT`, sysid=255)로 완전히 독립되어 있어 이번 수정이 공격 탐지 자체에는 영향 없음을 확인. 회귀 테스트로 `test_sustained_duplicate_does_not_flood`(최초 충돌 감지 후 동일 충돌이 30회 반복되어도 매번 None) 추가 — `python -m unittest tests.blue_agent.test_rules -v` 32/32 통과, 전체 스위트 72/73 통과(나머지 1건은 Windows 호스트 fastapi 미설치로 인한 test_main.py 환경 문제로 이 수정과 무관) 확인. 단, `--defaults` 플래그의 실제 ArduCopter SITL 바이너리 동작은 Linux VM에서 직접 재기동해봐야 최종 확인 가능(이 저장소는 Windows 호스트라 ardupilot 소스/바이너리 접근 불가)

---

## Phase 3 — Risk Engine

- [x] `app/blue_agent/risk/config.py` — 룰별 가중치, SAFE/WARNING/CRITICAL/EMERGENCY 임계값 (설정 파일에서 조정 가능)
- [x] `app/blue_agent/risk/engine.py` — 드론별 30초 슬라이딩 윈도우(`deque`) 기반 스코어링
- [x] `tests/blue_agent/test_risk_engine.py`

### 완료 로그
- 2026-07-08: app/blue_agent/risk/config.py — SEVERITY_SCORES(LOW/MEDIUM/HIGH/CRITICAL 점수), RULE_WEIGHTS(룰별 가중치 배수), RISK_THRESHOLDS(SAFE/WARNING/CRITICAL/EMERGENCY 임계값) 정의 + score_for()/level_for() 헬퍼 작성. 기존 app/blue_agent/config.py 골격은 이 파일 값을 감싸는 얇은 어댑터로 전환(BlueAgentConfig.rule_weights/risk_thresholds가 risk/config.py를 원본으로 채워짐), 값의 실체는 risk/config.py 한 곳에서만 관리
- 2026-07-08: app/blue_agent/risk/engine.py — `RiskEngine` 신규 작성. `ALL_RULES`(기본값, 주입 가능)를 이벤트에 통과시켜 나온 `RuleResult`들을 드론별 `deque[(ts, score)]`에 쌓고, 매 접근마다 WINDOW_SECONDS(30초)보다 오래된 항목을 왼쪽에서 제거해 슬라이딩 윈도우를 유지 — 남은 점수 합으로 SAFE/WARNING/CRITICAL/EMERGENCY 등급 산출. `process_event()`(룰 실행+반영), `record_results()`(계산된 결과 직접 반영), `current_assessment()`(신규 반영 없이 현재 상태만 조회) 3개 메서드로 분리. rules 인자 주입은 baseline 학습형 룰이 섞인 ALL_RULES 대신 고정 결과를 내는 가짜 룰로 테스트하기 위함
- 2026-07-08: tests/blue_agent/test_risk_engine.py — `FixedRule`(고정 severity 반환)·`SilentRule`(항상 None) 가짜 룰을 주입해 RiskEngine 집계 로직만 검증하는 단위 테스트 8개 신규 작성: 무반응 시 None 반환, 단일 LOW가 SAFE 유지, MEDIUM 반복 누적이 WARNING 돌파, CRITICAL 누적이 EMERGENCY 도달, 한 이벤트에 여러 룰이 반응할 때 점수 합산, 드론 간 점수 격리, 30초 윈도우 밖 항목 제거, 윈도우 안 항목은 유지. 전체 스위트(`python -m unittest discover -s tests`) 47개 전부 OK로 회귀 없음 확인

**Phase 3 완료 (3/3).** 다음 Phase(4 — AI Threat Analyzer) 시작 전 사용자 확인 대기.

---

## Phase 4 — AI Threat Analyzer

- [x] `app/blue_agent/ai/provider.py` — `LLMProvider` ABC (`analyze(events, rule_results) -> ThreatAnalysis`)
- [x] `app/blue_agent/ai/openai_provider.py` — 기본 구현체
- [x] `app/blue_agent/ai/prompts.py` — 시스템 프롬프트
- [x] CRITICAL/EMERGENCY 진입 시점에만 호출하는 연동 로직 (매 이벤트 호출 금지 — 비용/레이턴시)

### 완료 로그
- 2026-07-08: `app/blue_agent/ai/provider.py` — `LLMProvider` ABC와 `ThreatAnalysis` 결과 dataclass 추가 (openai_provider.py 등 구현체가 상속할 인터페이스)
- 2026-07-08: `app/blue_agent/ai/prompts.py` — ThreatAnalysis 필드와 1:1 대응하는 JSON 응답을 강제하는 시스템 프롬프트 추가
- 2026-07-08: `app/blue_agent/ai/openai_provider.py` — `OpenAIProvider` 구현체 추가 (OPENAI_API_KEY/OPENAI_MODEL 환경변수 사용, JSON 응답 파싱, 실패 시 attack_type="Unknown"으로 안전하게 폴백)
- 2026-07-08: `app/blue_agent/ai/analyzer.py` — `ThreatAnalyzerService` 신규 작성. 드론별 이전 위험 등급을 기억해뒀다가 SAFE/WARNING → CRITICAL/EMERGENCY로 "새로" 진입하는 전이 순간에만 `LLMProvider.analyze()` 호출 (동일 등급 유지 중에는 재호출 안 함). `note_event()`로 드론별 최근 이벤트를 소량 버퍼링해 analyze() 호출 시 근거 자료로 전달. `app/main.py`의 `_broadcast_loop()`에 5줄 훅 추가: `event_engine.ingest_packet()` 반환값을 `risk_engine.process_event()`에 통과시키고, 결과가 있으면 `threat_analyzer.on_assessment()` 호출 (기존에는 이 반환값이 버려지고 있었음 — RiskEngine이 실제 패킷 흐름에 연결되지 않던 갭을 이 작업으로 해소)

**Phase 4 완료 (4/4).** 다음 Phase(5 — Response Engine) 시작 전 사용자 확인 대기.

---

## Phase 5 — Response Engine (자동 + 수동)

- [x] `app/blue_agent/response/strategy.py` — `ResponseStrategy` ABC + `Log`/`Alert`/`Drop`/`Block` 전략
- [x] `app/blue_agent/response/engine.py` — Risk Level → 전략 자동 선택
- [x] `app/main.py`: `api_command()` 명령 전송 직전 차단 훅 (BLOCK 상태인 드론은 신규 명령 거부)
- [x] `/ws/blue_agent` 수신 메시지로 오퍼레이터 수동 조치 처리: `{"type":"defense_action","drone_id":...,"action":"BLOCK"|"UNBLOCK"|"FORCE_RTL"|"DISCONNECT"}`
- [x] `tests/blue_agent/test_response_engine.py`

### 완료 로그
- 2026-07-08: app/blue_agent/response/strategy.py — ResponseStrategy ABC 및 Log/Alert/Drop/Block 4개 전략 구현 (SAFE~EMERGENCY 1:1 대응, Block만 blocked=True로 명령 차단 신호)
- 2026-07-08: app/blue_agent/response/engine.py — `ResponseEngine` 구현. `on_assessment()`가 등급별 전략을 자동 선택·적용하고 드론별 `_blocked` 상태를 갱신, `is_blocked()`로 Task 3 훅에 제공. `apply_manual_action()`으로 오퍼레이터의 BLOCK/UNBLOCK/FORCE_RTL/DISCONNECT 수동 조치 처리 (FORCE_RTL은 `send_set_mode(6)`, DISCONNECT는 `connector.stop()` 사용). 순환 임포트 방지를 위해 connector는 호출자가 주입하는 방식으로 설계. `response_engine` 싱글턴 추가
- 2026-07-08: app/main.py — `_broadcast_loop()`의 기존 `if assessment is not None:` 블록에 `response_engine.on_assessment(assessment)` 1줄 추가해 자동 대응 경로를 실시간 패킷 처리에 연결. `api_command()`의 `is_ready()` 체크 직후에 `response_engine.is_blocked(req.drone_id)` 차단 훅 추가 — BLOCK 상태인 드론에는 신규 명령을 403으로 거부 (기존 SITL 미연결(503) 처리와 별개 경로, 다른 명령 로직은 변경 없음)
- 2026-07-08: app/main.py — `/ws/blue_agent` WebSocket 엔드포인트 신규 추가 (기존 `/ws/gcs`, `/ws/attacker`는 변경 없음). `blue_mgr`로 연결 수립 후 텍스트 메시지를 JSON 파싱해 `type=="defense_action"`인 것만 처리, `drone_id`/`action`을 꺼내 `DRONES.get(drone_id)`로 커넥터를 조회하고 `response_engine.apply_manual_action()`에 전달. 처리 결과는 `{"type":"defense_action_result", ...}`로 `blue_mgr.broadcast()`해 모든 대시보드 클라이언트에 반영
- 2026-07-08: tests/blue_agent/test_response_engine.py — `ResponseEngine` 단위 테스트 14개 작성. `on_assessment()`는 SAFE/WARNING/CRITICAL/EMERGENCY 4개 등급이 각각 LOG/ALERT/DROP/BLOCK 전략을 선택하는지, EMERGENCY만 `is_blocked()`를 True로 만들고 이후 SAFE 재평가 시 다시 False로 풀리는지 검증. `apply_manual_action()`은 BLOCK/UNBLOCK 상태 전환과 FORCE_RTL(가짜 커넥터로 `send_set_mode(6)` 호출 확인)/DISCONNECT(`stop()` 호출 확인) 성공 경로, connector=None 실패 경로, 알 수 없는 action 처리까지 커버. `unittest.TestCase` 기반, 실제 SITLConnector 대신 FakeConnector 스텁 사용. `python -m unittest` 실행으로 14/14 통과 확인

**Phase 5 완료 (5/5).** 다음 Phase(6 — MITRE Mapping) 시작 전 사용자 확인 대기.

---

## Phase 6 — MITRE Mapping

- [x] `app/blue_agent/services/mitre_mapper.py` — 룰 ID → (ATT&CK, ATT&CK for ICS, D3FEND) 매핑 테이블
- [x] `tests/blue_agent/test_mitre_mapper.py`

### 완료 로그
- 2026-07-08: app/blue_agent/services/__init__.py, app/blue_agent/services/mitre_mapper.py — `MitreMapping` frozen dataclass(attack/attack_ics/d3fend) + 10종 rule_id 전체 매핑 테이블 `MITRE_MAPPING`과 `mapping_for()` 조회 함수 신규 작성. sysid_spoofing/duplicate_sysid/unsigned_packet/packet_replay/rtl_abuse/unknown_mode_change는 이 프로젝트가 실제 구현한 MAVLink v2 서명 방어(§3.3)로 막을 수 있는 "발신자 신원·무결성 불신" 계열이라 D3FEND "Message Authentication"(duplicate_sysid만 교차 채널 신원 충돌이라 "Mutual Authentication")으로 묶었고, gps_injection은 서명으로 막을 수 없는 센서 계층 공격이라 "Platform Monitoring", sequence_anomaly는 인증이 아닌 통계적 이상탐지라 "Network Traffic Analysis", command_flood는 "Rate Limiting", flight_termination은 "Execution Allowlisting"으로 개별 매핑
- 2026-07-08: tests/blue_agent/test_mitre_mapper.py — 10종 rule_id 전체가 미매핑 플레이스홀더 없이 실제 매핑을 갖는지, `mapping_for()`가 known rule_id(gps_injection, duplicate_sysid)에 정확한 값을 반환하는지, 미등록 rule_id에는 "미매핑" 플레이스홀더로 폴백하는지 검증하는 unittest 5건 추가. `python -m unittest tests.blue_agent.test_mitre_mapper -v` 전체 통과 확인

---

## Phase 7 — Dashboard (`/blue_agent`)

- [x] `app/blue_agent/dashboard/router.py` — `/ws/blue_agent` 엔드포인트, `blue_mgr` 관리, 수동 조치 명령 라우팅 (Phase 5에서 `app/main.py`에 이미 구현됨 — 중복 라우터 생성하지 않음)
- [x] `app/main.py`: `app.mount("/blue_agent", StaticFiles(directory="frontend/blue_agent", html=True), name="blue_agent")`
- [x] `frontend/blue_agent/index.html` — 레이아웃 + 로직 단일 파일: Leaflet 지도 + Current Attack/Timeline/Risk Score 패널 + 드론 상태 + Active Rules + MITRE 매핑 + 방어 조치 버튼 (`frontend/gcs/index.html` 패턴과 동일하게 inline `<style>`/`<script>`로 구현, 별도 `main.js` 없음)

### 완료 로그
- 2026-07-08: BLUE_AGENT_PLAN.md — Task 1은 Phase 5에서 이미 구현된 `/ws/blue_agent`(app/main.py 라인 197-217)로 충족됨을 확인해 완료 처리, 별도 `dashboard/router.py` 생성 안 함. `frontend/gcs/index.html` 전체를 읽어 실제 프론트엔드가 별도 main.js 없이 단일 파일(inline style+script) 구조임을 확인 — Task 3/4를 `frontend/blue_agent/index.html` 단일 파일로 통합하기로 계획 수정
- 2026-07-08: app/main.py — 기존 `/attacker`, `/gcs` static mount 바로 뒤에 `app.mount("/blue_agent", StaticFiles(directory="frontend/blue_agent", html=True), name="blue_agent")` 1줄 추가 (기존 두 마운트는 정렬만 맞추고 동작 변경 없음)
- 2026-07-08: app/blue_agent/services/dashboard_events.py, app/main.py, tests/blue_agent/test_dashboard_events.py — `build_detection_message()` 신규 작성(RiskAssessment → rule_id별 MITRE 매핑 포함 "detection" 메시지 직렬화). `_broadcast_loop()`의 기존 `if assessment is not None:` 블록 안, `response_engine.on_assessment(assessment)` 다음 줄에 `await blue_mgr.broadcast(build_detection_message(assessment))` 1줄만 추가 — 대시보드 Current Attack/Timeline/Risk Score/Active Rules 패널의 데이터 소스 확보. 단위 테스트 2건(rules 매핑 포함 정상 케이스, triggered 없을 때 빈 리스트) 통과 확인
- 2026-07-08: frontend/blue_agent/index.html — Task 3 단일 파일 대시보드 신규 작성. Leaflet 지도(위험도별 색상 마커, GPS 미수신 시 HOME_LATLON 폴백), 드론 상태 카드 + 다중 선택(mousedown 기반, GCS와 동일 패턴), Current Attack/Risk Score/Active Rules(MITRE 태그 포함) 패널은 선택된 드론 중 가장 위험도가 높은 드론 기준으로 표시, BLOCK/UNBLOCK/FORCE_RTL/DISCONNECT 4개 방어 조치 버튼(`/ws/blue_agent`에 `defense_action` 전송), Timeline 패널은 20Hz로 반복 수신되는 detection 메시지에서 새로 활성화된 rule_id만 골라 기록하는 rising-edge 중복 제거 로직 적용. `/ws/gcs`·`/ws/attacker`·REST API는 건드리지 않음

---

## Phase 8 — 통합 확인 및 문서화

- [ ] 기존 `/gcs`, `/attacker`, REST API 회귀 테스트 (정상 동작 재확인)
- [ ] `RUNBOOK.md`에 Blue Agent 섹션(포트/URL/시나리오) 추가
- [ ] `CLAUDE.md` 업데이트 여부 검토 (Blue Agent 관련 절대 규칙 추가할지 사용자와 확인)

### 완료 로그
- 2026-07-08: app/blue_agent/ai/openai_provider.py, tests/blue_agent/test_openai_provider.py — Task 1 회귀 테스트를 위해 VM에서 서버를 재기동하던 중 `OPENAI_API_KEY` 미설정 시 `OpenAI()` 생성자가 `OpenAIError`를 던지고, 이게 모듈 임포트 시점(`analyzer.py`의 `threat_analyzer = ThreatAnalyzerService()` 싱글턴)에 전파되어 `app/main.py` 임포트 자체가 실패 — `/gcs`·`/attacker`·REST API 전부 기동 불가가 되는 버그 발견. `OpenAIProvider.__init__`에서 `OpenAI()` 생성을 try/except로 감싸 실패 시 `self._client = None`으로 폴백하고, `analyze()` 앞단에 `self._client is None` 가드를 추가해 API 키 없이도 안전한 `ThreatAnalysis(attack_type="Unknown")`를 즉시 반환하도록 수정. 단위 테스트 2건 추가, 전체 테스트 70건 통과 확인 (OPENAI_API_KEY 미설정 상태로 검증)

---

## 진행 규칙 요약

1. Phase 순서대로 진행하되, 각 Phase 시작 전 이 파일을 다시 확인한다.
2. 작업 하나 끝날 때마다: 체크박스 갱신 → 완료 로그에 `- YYYY-MM-DD: <파일> — <한 줄 설명>` 추가 → 사용자에게 무엇을 왜 바꿨는지 보고.
3. 기존 파일 수정은 최소 훅 삽입으로 제한한다 (5줄 미만 원칙 유지).
4. 새 기능은 항상 `app/blue_agent/` 내부 새 파일로 우선 구현하고, 기존 파일에는 연결 지점만 추가한다.
