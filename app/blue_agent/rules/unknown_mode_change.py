"""unknown_mode_change — HEARTBEAT의 비행 모드가 알려지지 않은 값으로 전환되는 것 탐지.

CLAUDE.md에 문서화된 이 테스트베드의 정상 운용 모드는
STABILIZE/AUTO/GUIDED/LOITER/RTL/LAND 6종뿐이다. HeartbeatEvent.mode가
이 화이트리스트 밖의 값으로 "전환"되면(매 하트비트마다가 아니라 실제로
바뀔 때만) 알 수 없는 모드로 진입한 것으로 보고 HIGH로 탐지한다.
모드 자체는 SET_MODE 네이티브 메시지로 바뀌어 CommandEvent로 잡히지
않으므로(quirk 참고), HeartbeatEvent.mode 변화만이 유일한 관측 신호다.
"""
from __future__ import annotations

from app.blue_agent.models.events import HeartbeatEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult

KNOWN_MODES = {"STABILIZE", "AUTO", "GUIDED", "LOITER", "RTL", "LAND"}


class UnknownModeChangeRule(BaseRule):
    rule_id = "unknown_mode_change"
    severity = "HIGH"

    def __init__(self) -> None:
        self._last_mode: dict[str, str] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, HeartbeatEvent):
            return None

        last_mode = self._last_mode.get(event.drone_id)
        self._last_mode[event.drone_id] = event.mode

        if event.mode == last_mode:
            return None
        if event.mode in KNOWN_MODES:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"{event.drone_id} 비행 모드가 알 수 없는 값 '{event.mode}'로 전환 "
                f"(이전: '{last_mode or '알수없음'}') — 비인가 모드 전환 의심"
            ),
            evidence={
                "prev_mode": last_mode,
                "mode": event.mode,
                "known_modes": sorted(KNOWN_MODES),
                "armed": event.armed,
            },
        )
