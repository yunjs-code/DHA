"""unsigned_packet — 서명 채널에서 무서명 패킷으로의 전환(다운그레이드) 탐지.

MAVLink v2 서명(§3.3 방어, scripts/defense_signing.py)은 선택적으로 켜진다.
서명이 꺼진 상태의 정상 트래픽은 원래 전부 무서명이므로, 무서명 패킷 자체를
무조건 탐지 대상으로 삼으면 오탐이 쏟아진다.

과거에는 "이 드론 채널에서 서명된 패킷을 한 번이라도 관측했다"는 사실을
영구히 기억해두고, 그 이후 나타나는 모든 무서명 패킷을 계속 의심하는
방식이었다. 하지만 서명 실험(scripts/defense_signing.py)을 한 번이라도
돌린 드론은 그 뒤로 서명이 다시 꺼져도(=정상 GCS 트래픽이 원래 무서명이라)
사실상 모든 패킷이 영원히 HIGH로 잡혀 EMERGENCY까지 치솟고 드론 조작이
전부 차단되는 문제가 있었다.

그래서 "직전 패킷 대비 서명 상태 전환"만 본다: 바로 직전 패킷이 서명되어
있었는데 이번 패킷이 무서명이면(서명 -> 무서명 전환) 그 순간만 서명
우회/다운그레이드 시도로 간주한다. 그 다음부터 계속 무서명이 이어지는
것은(서명 자체가 다시 꺼진 정상 상태) 더 이상 반복 탐지하지 않는다.
"""
from __future__ import annotations

from app.blue_agent.models.events import CommandEvent, RawPacketEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult


class UnsignedPacketRule(BaseRule):
    rule_id = "unsigned_packet"
    severity = "HIGH"

    def __init__(self) -> None:
        self._last_signed: dict[str, bool] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, (CommandEvent, RawPacketEvent)):
            return None

        was_signed = self._last_signed.get(event.drone_id, False)
        self._last_signed[event.drone_id] = event.signed

        if event.signed or not was_signed:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"{event.drone_id} 채널이 서명 -> 무서명으로 전환됨 "
                f"(서명 우회/다운그레이드 의심)"
            ),
            evidence={
                "event_type": type(event).__name__,
                "signed": event.signed,
            },
        )
