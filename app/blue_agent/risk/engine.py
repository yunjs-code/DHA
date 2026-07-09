"""RiskEngine — SecurityEvent를 룰 전체에 통과시켜 드론별 위험도를 집계한다.

base.py의 문서대로 "RuleEngine 역할"은 이 클래스가 겸한다: ALL_RULES를
순회하며 event.evaluate()를 호출하고, 발생한 RuleResult들을 드론별
deque에 (ts, score) 쌍으로 쌓는다. 매 호출마다 WINDOW_SECONDS(30초)보다
오래된 항목을 왼쪽에서 제거해 슬라이딩 윈도우를 유지하고, 남은 항목의
점수 합으로 SAFE/WARNING/CRITICAL/EMERGENCY 등급을 매긴다.

rules 인자를 주입할 수 있게 한 이유: ALL_RULES의 룰 인스턴스는 대부분
baseline 학습형(sysid_spoofing 등)이라 실제 룰로 테스트하면 학습 상태에
따라 결과가 흔들린다. test_risk_engine.py는 결과가 고정된 가짜 룰을
주입해 집계 로직(윈도우 만료·점수 합산·등급 산출)만 검증한다.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from app.blue_agent.models.events import SecurityEvent
from app.blue_agent.risk.config import WINDOW_SECONDS, level_for, score_for
from app.blue_agent.rules import ALL_RULES, BaseRule, RuleResult


@dataclass
class RiskAssessment:
    """특정 시점에 특정 드론의 위험도 조회 결과."""

    drone_id: str
    level: str
    score: float
    triggered: list[RuleResult] = field(default_factory=list)


class RiskEngine:
    """드론별 30초 슬라이딩 윈도우 기반 위험도 스코어링."""

    def __init__(self, rules: list[BaseRule] | None = None) -> None:
        self._rules = rules if rules is not None else ALL_RULES
        self._windows: dict[str, deque[tuple[float, float]]] = {}

    def _window_for(self, drone_id: str, now: float) -> deque[tuple[float, float]]:
        window = self._windows.setdefault(drone_id, deque())
        while window and now - window[0][0] > WINDOW_SECONDS:
            window.popleft()
        return window

    def process_event(self, event: SecurityEvent) -> RiskAssessment | None:
        """event를 모든 룰에 통과시키고 반응이 있으면 위험도를 갱신한다.

        어떤 룰도 반응하지 않으면(RuleResult 없음) None을 반환한다.
        """
        triggered = [
            result
            for rule in self._rules
            if (result := rule.evaluate(event)) is not None
        ]
        if not triggered:
            return None
        return self.record_results(event.drone_id, triggered)

    def record_results(self, drone_id: str, results: list[RuleResult]) -> RiskAssessment:
        """이미 계산된 RuleResult 목록을 드론 윈도우에 직접 반영한다."""
        now = time.time()
        window = self._window_for(drone_id, now)
        for result in results:
            window.append((result.ts, score_for(result.severity, result.rule_id)))

        total = sum(score for _, score in window)
        return RiskAssessment(drone_id=drone_id, level=level_for(total), score=total, triggered=results)

    def current_assessment(self, drone_id: str) -> RiskAssessment:
        """새 이벤트 없이 현재 윈도우 상태만 조회한다 (만료 항목은 제거)."""
        window = self._window_for(drone_id, time.time())
        total = sum(score for _, score in window)
        return RiskAssessment(drone_id=drone_id, level=level_for(total), score=total, triggered=[])


risk_engine = RiskEngine()
