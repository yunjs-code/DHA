"""ResponseEngine — RiskAssessment.level에 맞는 ResponseStrategy를 자동 선택해 적용한다.

_STRATEGY_FOR_LEVEL은 risk/config.py의 네 등급(SAFE/WARNING/CRITICAL/EMERGENCY)과
1:1로 대응한다. on_assessment()가 자동 경로(예: _broadcast_loop에서 매 assessment마다
호출)이고, 오퍼레이터의 수동 조치(BLOCK/UNBLOCK/FORCE_RTL/DISCONNECT, `/ws/blue_agent`가
Phase 7에서 라우팅)는 apply_manual_action()이 처리한다.

드론별 "현재 BLOCK 여부"는 마지막 자동/수동 조치 결과로 결정되는 하나의 상태이므로
_blocked 딕셔너리 하나로만 관리한다 — 자동으로 EMERGENCY에 들어가 BLOCK되었어도
오퍼레이터가 UNBLOCK을 보내면 해제되고, 그 반대도 마찬가지로 동작해야 하기 때문이다.

FORCE_RTL/DISCONNECT는 실제 SITL 연결(SITLConnector)이 있어야 실행 가능한데,
app/main.py가 app.blue_agent.*를 임포트하는 구조라 이 모듈이 app.main을 다시
임포트하면 순환 임포트가 생긴다. 그래서 이 두 액션은 connector 인스턴스를
인자로 받아 호출자(현재는 main.py의 소규모 래퍼, Phase 7부터는 대시보드 라우터)가
DRONES에서 꺼내 넘겨주는 방식으로 설계했다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.blue_agent.response.strategy import (
    AlertStrategy,
    BlockStrategy,
    DropStrategy,
    LogStrategy,
    ResponseAction,
    ResponseStrategy,
)
from app.blue_agent.risk.engine import RiskAssessment

log = logging.getLogger("blue_agent.response")

_STRATEGY_FOR_LEVEL: dict[str, ResponseStrategy] = {
    "SAFE": LogStrategy(),
    "WARNING": AlertStrategy(),
    "CRITICAL": DropStrategy(),
    "EMERGENCY": BlockStrategy(),
}

_RTL_MODE_ID = 6  # ArduCopter RTL 모드 번호 (CLAUDE.md 모드 매핑 참고)


@dataclass
class ManualActionResult:
    """오퍼레이터 수동 조치(apply_manual_action) 처리 결과."""

    drone_id: str
    action: str
    success: bool
    message: str


class ResponseEngine:
    """Risk Level 기반 자동 대응 + 오퍼레이터 수동 조치를 함께 관리한다."""

    def __init__(self) -> None:
        self._blocked: dict[str, bool] = {}

    def on_assessment(self, assessment: RiskAssessment) -> ResponseAction:
        """RiskAssessment 등급에 맞는 전략을 자동 적용하고 BLOCK 상태를 갱신한다."""
        strategy = _STRATEGY_FOR_LEVEL.get(assessment.level, LogStrategy())
        action = strategy.apply(assessment)
        self._blocked[assessment.drone_id] = action.blocked
        return action

    def is_blocked(self, drone_id: str) -> bool:
        """api_command()가 신규 명령을 거부할지 판단할 때 참조하는 상태."""
        return self._blocked.get(drone_id, False)

    def apply_manual_action(self, drone_id: str, action: str, connector=None) -> ManualActionResult:
        """오퍼레이터가 `/ws/blue_agent`로 보낸 defense_action을 처리한다.

        connector는 FORCE_RTL/DISCONNECT에서만 필요하다(SITLConnector 인스턴스).
        순환 임포트를 피하려고 이 모듈에서 app.main.DRONES를 직접 참조하지 않고
        호출자가 넘겨주도록 한다.
        """
        if action == "BLOCK":
            self._blocked[drone_id] = True
            return ManualActionResult(drone_id, action, True, f"[{drone_id}] 오퍼레이터 수동 BLOCK")

        if action == "UNBLOCK":
            self._blocked[drone_id] = False
            return ManualActionResult(drone_id, action, True, f"[{drone_id}] 오퍼레이터 수동 UNBLOCK")

        if action == "FORCE_RTL":
            if connector is None or not connector.send_set_mode(_RTL_MODE_ID):
                return ManualActionResult(drone_id, action, False, f"[{drone_id}] FORCE_RTL 실패 — 연결 없음")
            return ManualActionResult(drone_id, action, True, f"[{drone_id}] FORCE_RTL 전송 완료")

        if action == "DISCONNECT":
            if connector is None:
                return ManualActionResult(drone_id, action, False, f"[{drone_id}] DISCONNECT 실패 — 연결 없음")
            connector.stop()
            self._blocked[drone_id] = True
            return ManualActionResult(drone_id, action, True, f"[{drone_id}] DISCONNECT 완료")

        return ManualActionResult(drone_id, action, False, f"알 수 없는 action: {action}")


response_engine = ResponseEngine()
