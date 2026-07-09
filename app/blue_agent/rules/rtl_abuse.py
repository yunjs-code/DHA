"""rtl_abuse — COMMAND_LONG 기반 MAV_CMD_NAV_RETURN_TO_LAUNCH(20) 관측 탐지.

이 테스트베드에서 RTL로 전환하는 정상 경로는 두 곳뿐이다: GCS UI
(POST /api/command cmd=RTL, app/sitl.py)와 app/attacks.py의 att01_ RTL
주입 공격 모두 `set_mode_send`/`set_mode_encode` 네이티브 SET_MODE
메시지만 사용하며, COMMAND_LONG으로 MAV_CMD_NAV_RETURN_TO_LAUNCH(20)를
보내는 코드는 이 코드베이스 어디에도 없다(app/sitl.py의 명령 이름
매핑에 20:"RTL"이 있는 건 관측용 디코딩일 뿐 발신용이 아님). 따라서
COMMAND_LONG(20)이 관측되면 그 자체로 이 시스템이 쓰지 않는 대체 채널을
통한 비인가 RTL 강제이므로 baseline 학습 없이 즉시 HIGH로 판단한다.
"""
from __future__ import annotations

from app.blue_agent.models.events import CommandEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult

MAV_CMD_NAV_RETURN_TO_LAUNCH = 20


class RtlAbuseRule(BaseRule):
    rule_id = "rtl_abuse"
    severity = "HIGH"

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, CommandEvent):
            return None
        if event.command != MAV_CMD_NAV_RETURN_TO_LAUNCH:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"{event.drone_id}에 COMMAND_LONG 기반 MAV_CMD_NAV_RETURN_TO_LAUNCH(20) 관측 — "
                f"정상 경로는 SET_MODE 네이티브 메시지만 사용, 비인가 RTL 강제 의심"
            ),
            evidence={
                "command": event.command,
                "params": event.params,
                "sysid": event.sysid,
            },
        )
