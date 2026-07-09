"""Blue Agent 설정 로더.

실제 가중치·임계값은 app/blue_agent/risk/config.py가 원본이며,
이 로더는 그 값을 BlueAgentConfig로 감싸 반환하는 얇은 어댑터다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.blue_agent.risk import config as risk_config


@dataclass
class BlueAgentConfig:
    rule_weights: dict[str, float] = field(default_factory=dict)
    risk_thresholds: dict[str, float] = field(default_factory=dict)


def load_config() -> BlueAgentConfig:
    """risk/config.py의 RULE_WEIGHTS·RISK_THRESHOLDS를 담아 반환한다."""
    return BlueAgentConfig(
        rule_weights=dict(risk_config.RULE_WEIGHTS),
        risk_thresholds=dict(risk_config.RISK_THRESHOLDS),
    )
