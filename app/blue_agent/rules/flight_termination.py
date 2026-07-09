"""flight_termination — MAV_CMD_DO_FLIGHTTERMINATION(185) 명령 관측 탐지.

이 시스템의 정상 GCS UI(POST /api/command)는 ARM/DISARM/TAKEOFF/LAND/RTL/
GOTO/SET_MODE만 노출하며 비행 강제 종료(FLIGHTTERMINATION)는 절대 보내지
않는다. 따라서 이 명령이 담긴 COMMAND_LONG이 관측되면 그 자체로 정상
경로가 아니며, 성공 시 드론이 즉시 모터를 정지(추락)하는 가장 파괴적인
명령이므로 baseline 학습 없이 즉시 CRITICAL로 판단한다.
"""
from __future__ import annotations

from app.blue_agent.models.events import CommandEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult

MAV_CMD_DO_FLIGHTTERMINATION = 185


class FlightTerminationRule(BaseRule):
    rule_id = "flight_termination"
    severity = "CRITICAL"

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, CommandEvent):
            return None
        if event.command != MAV_CMD_DO_FLIGHTTERMINATION:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"{event.drone_id}에 MAV_CMD_DO_FLIGHTTERMINATION(185) 관측 — "
                f"정상 GCS UI는 이 명령을 보내지 않음, 비행 강제 종료 공격 의심"
            ),
            evidence={
                "command": event.command,
                "params": event.params,
                "sysid": event.sysid,
            },
        )
