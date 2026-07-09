"""ResponseStrategy — Risk Level별 자동 대응 전략.

RiskEngine이 산출한 RiskAssessment(SAFE/WARNING/CRITICAL/EMERGENCY)를 받아
등급에 맞는 조치를 실행한다. 네 등급에 각각 하나씩 대응하는 네 가지 전략을
둔다: Log(SAFE) -> Alert(WARNING) -> Drop(CRITICAL) -> Block(EMERGENCY).
등급이 올라갈수록 조치 강도가 세지는 단조 증가 구조이며, 실제로 신규
명령을 거부하는 하드 제재는 Block 전략만 수행한다(ResponseAction.blocked).
그 아래 단계(Log/Alert/Drop)는 로그 레벨과 대시보드 표시용 메시지만
달라지고 명령 전송 자체를 막지는 않는다 — 오탐으로 인해 드론 운용이
막히는 것을 피하기 위해, 실제 차단은 EMERGENCY(명백한 공격 패턴 확정)
시에만 발동한다.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.blue_agent.risk.engine import RiskAssessment

log = logging.getLogger("blue_agent.response")


@dataclass
class ResponseAction:
    """전략 적용 결과 — ResponseEngine과 대시보드(Phase 7)가 공통으로 참조한다."""

    strategy: str
    drone_id: str
    level: str
    message: str
    blocked: bool = False


class ResponseStrategy(ABC):
    """Risk Level 하나에 대응하는 자동 대응 전략의 공통 인터페이스."""

    name: str = "base"

    @abstractmethod
    def apply(self, assessment: RiskAssessment) -> ResponseAction:
        """assessment를 받아 조치를 수행하고 그 결과를 ResponseAction으로 반환한다."""
        raise NotImplementedError


class LogStrategy(ResponseStrategy):
    """SAFE — 조용히 기록만 한다."""

    name = "LOG"

    def apply(self, assessment: RiskAssessment) -> ResponseAction:
        message = f"[{assessment.drone_id}] SAFE (score={assessment.score:.1f})"
        log.debug(message)
        return ResponseAction(
            strategy=self.name, drone_id=assessment.drone_id,
            level=assessment.level, message=message, blocked=False,
        )


class AlertStrategy(ResponseStrategy):
    """WARNING — 경고 로그를 남긴다(명령 차단은 하지 않음)."""

    name = "ALERT"

    def apply(self, assessment: RiskAssessment) -> ResponseAction:
        message = f"[{assessment.drone_id}] WARNING 진입 (score={assessment.score:.1f})"
        log.warning(message)
        return ResponseAction(
            strategy=self.name, drone_id=assessment.drone_id,
            level=assessment.level, message=message, blocked=False,
        )


class DropStrategy(ResponseStrategy):
    """CRITICAL — 심각 로그를 남긴다. 오탐 여지를 감안해 명령 차단까지는 하지 않는다."""

    name = "DROP"

    def apply(self, assessment: RiskAssessment) -> ResponseAction:
        message = f"[{assessment.drone_id}] CRITICAL 진입 (score={assessment.score:.1f}) — 감시 강화"
        log.error(message)
        return ResponseAction(
            strategy=self.name, drone_id=assessment.drone_id,
            level=assessment.level, message=message, blocked=False,
        )


class BlockStrategy(ResponseStrategy):
    """EMERGENCY — 신규 명령을 거부한다(BLOCK 상태 진입)."""

    name = "BLOCK"

    def apply(self, assessment: RiskAssessment) -> ResponseAction:
        message = f"[{assessment.drone_id}] EMERGENCY 진입 (score={assessment.score:.1f}) — 명령 차단"
        log.critical(message)
        return ResponseAction(
            strategy=self.name, drone_id=assessment.drone_id,
            level=assessment.level, message=message, blocked=True,
        )
