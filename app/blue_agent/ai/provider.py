"""LLMProvider ABC — 이벤트·룰 판정 결과를 받아 AI 기반 위협 분석을 생성하는 인터페이스.

RiskEngine까지는 규칙 기반 점수 집계와 SAFE/WARNING/CRITICAL/EMERGENCY 등급
산출만 담당하고, "왜 위험한지"에 대한 자연어 설명이나 공격 유형 추정은 하지
않는다. LLMProvider는 이 갭을 메우는 자리이며, 비용/레이턴시 때문에 매
이벤트마다가 아니라 드론의 위험 등급이 CRITICAL/EMERGENCY로 새로 진입하는
순간에만 호출된다 (호출 시점 판단 로직은 이 Phase의 마지막 작업에서 별도 구현).

구현체를 이 파일이 아닌 openai_provider.py로 분리한 이유: 이후 다른 provider
(예: Claude)를 추가할 때 이 ABC와 ThreatAnalysis는 그대로 두고 새 구현
파일만 추가하면 되게 하기 위함.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.blue_agent.models.events import SecurityEvent
from app.blue_agent.rules.base import RuleResult


@dataclass
class ThreatAnalysis:
    """LLMProvider.analyze()의 결과."""

    drone_id: str
    summary: str              # 사람이 읽는 상황 요약 (한국어)
    attack_type: str          # 추정 공격 유형 (예: "GPS Spoofing", "Command Injection", "Unknown")
    confidence: float         # 0.0~1.0
    recommended_action: str   # 자연어 권고 (실제 자동 대응은 Phase 5 Response Engine이 담당)
    ts: float = field(default_factory=time.time)


class LLMProvider(ABC):
    """AI 기반 위협 분석기 인터페이스. openai_provider.py 등 구현체가 상속한다."""

    @abstractmethod
    def analyze(self, events: list[SecurityEvent], rule_results: list[RuleResult]) -> ThreatAnalysis:
        """최근 이벤트·룰 판정 결과를 받아 ThreatAnalysis를 반환한다."""
        raise NotImplementedError
