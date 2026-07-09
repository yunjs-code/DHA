"""ThreatAnalyzerService — RiskEngine의 위험 등급이 CRITICAL/EMERGENCY로

"새로" 진입하는 순간에만 LLMProvider.analyze()를 호출하는 연동 로직.

매 이벤트마다 호출하면 비용/레이턴시 문제가 생기므로(openai_provider.py 참고),
드론별 "이전 위험 등급"을 기억해뒀다가 SAFE/WARNING -> CRITICAL/EMERGENCY로
넘어가는 전이(edge) 순간에만 analyze()를 호출한다. CRITICAL/EMERGENCY가
유지되는 동안에는 반복 호출하지 않는다.

analyze()에 넘길 events는 RiskAssessment에 담겨 있지 않으므로(RiskAssessment는
triggered RuleResult만 가짐), note_event()로 드론별 최근 이벤트를 소량 버퍼링해
두었다가 전이 시점에 근거 자료로 함께 전달한다.
"""
from __future__ import annotations

from collections import deque

from app.blue_agent.ai.openai_provider import OpenAIProvider
from app.blue_agent.ai.provider import LLMProvider, ThreatAnalysis
from app.blue_agent.models.events import SecurityEvent
from app.blue_agent.risk.engine import RiskAssessment

_ALERT_LEVELS = {"CRITICAL", "EMERGENCY"}
_EVENT_BUFFER_SIZE = 20


class ThreatAnalyzerService:
    """드론별 위험 등급 변화를 추적해 CRITICAL/EMERGENCY 진입 시에만 AI 분석을 트리거한다."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider or OpenAIProvider()
        self._last_level: dict[str, str] = {}
        self._recent_events: dict[str, deque[SecurityEvent]] = {}

    def note_event(self, event: SecurityEvent) -> None:
        """analyze() 호출 시 근거로 쓸 이벤트를 드론별 버퍼에 쌓는다."""
        buf = self._recent_events.setdefault(event.drone_id, deque(maxlen=_EVENT_BUFFER_SIZE))
        buf.append(event)

    def on_assessment(self, assessment: RiskAssessment) -> ThreatAnalysis | None:
        """CRITICAL/EMERGENCY로 새로 진입한 경우에만 analyze()를 호출해 결과를 반환한다."""
        drone_id = assessment.drone_id
        previous = self._last_level.get(drone_id)
        self._last_level[drone_id] = assessment.level

        if assessment.level not in _ALERT_LEVELS or previous in _ALERT_LEVELS:
            return None

        events = list(self._recent_events.get(drone_id, ()))
        return self._provider.analyze(events, assessment.triggered)


threat_analyzer = ThreatAnalyzerService()
