"""BaseRule — 모든 탐지 룰의 공통 인터페이스.

RuleEngine(Phase 3의 Risk Engine이 소비)은 app.blue_agent.rules 패키지에
자동 등록된 룰 인스턴스들을 순회하며 각 SecurityEvent를 evaluate()에 전달한다.
룰은 인스턴스 상태(예: 드론별 이전 seq, 최근 발생 시각 목록)를 들고 있을 수 있으며,
그런 상태는 각 룰 구현체가 자체적으로 dict 등으로 관리한다.

rule_id는 config.py의 BlueAgentConfig.rule_weights 딕셔너리 키와 짝을 맞춘다
(Phase 3에서 룰별 가중치를 매길 때 사용).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.blue_agent.models.events import SecurityEvent


@dataclass
class RuleResult:
    """룰이 이벤트에서 이상 징후를 발견했을 때 반환하는 결과."""

    rule_id: str
    drone_id: str
    severity: str  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    message: str
    evidence: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class BaseRule(ABC):
    """모든 탐지 룰이 상속하는 추상 베이스."""

    rule_id: str = "base_rule"
    severity: str = "LOW"

    @abstractmethod
    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        """event를 검사해 이상 징후가 있으면 RuleResult, 없으면 None을 반환한다."""
        raise NotImplementedError
