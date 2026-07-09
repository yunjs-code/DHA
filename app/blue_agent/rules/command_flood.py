"""command_flood — 짧은 시간 내 동일 드론에 반복 명령(COMMAND_LONG) 관측 탐지.

정상 GCS 조작은 사용자가 버튼을 누를 때마다 발생하므로 초당 여러 건이
나오지 않는다. 짧은 시간창(WINDOW_SECONDS) 안에 임계치(THRESHOLD)를
초과하는 CommandEvent가 같은 drone_id에서 발생하면 자동화된 명령 주입
(플러딩/DoS 성격의 공격)으로 판단한다.

과거에는 EventEngine.ingest_packet()이 COMMAND_LONG(실제 GCS 명령)과
COMMAND_ACK(드론의 응답)를 둘 다 CommandEvent로 매핑하는데, 이 룰이 그
구분 없이 모든 CommandEvent를 카운트했다. 명령 하나당 최소 COMMAND_LONG
1건 + COMMAND_ACK 1건이 함께 발생하므로 실제 임계치가 조용히 절반 이하로
낮아져, 정상적인 GCS 사용만으로도 플러딩 오탐이 발생했다.

그래서 CommandEvent.msg_name이 COMMAND_ACK인 이벤트(드론의 응답)는 카운트에서
제외하고, 실제 명령(COMMAND_LONG, 또는 ingest_attack()이 COMMAND_LONG으로
취급하는 ATT-01류 명령 주입 공격 메타)만 센다.
"""
from __future__ import annotations

from collections import deque

from app.blue_agent.models.events import CommandEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult

WINDOW_SECONDS = 2.0
THRESHOLD = 5


class CommandFloodRule(BaseRule):
    rule_id = "command_flood"
    severity = "MEDIUM"

    def __init__(self) -> None:
        self._recent: dict[str, deque[float]] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, CommandEvent):
            return None
        if event.msg_name == "COMMAND_ACK":
            return None

        history = self._recent.setdefault(event.drone_id, deque())
        history.append(event.ts)
        while history and event.ts - history[0] > WINDOW_SECONDS:
            history.popleft()

        if len(history) <= THRESHOLD:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"{event.drone_id}에 {WINDOW_SECONDS}초 내 명령 {len(history)}건 관측 "
                f"(임계치 {THRESHOLD}건 초과) — 명령 플러딩 의심"
            ),
            evidence={
                "count": len(history),
                "window_seconds": WINDOW_SECONDS,
                "threshold": THRESHOLD,
                "last_command": event.command,
            },
        )
