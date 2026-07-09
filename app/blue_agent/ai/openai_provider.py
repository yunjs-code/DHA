"""LLMProvider 기본 구현체 — OpenAI Chat Completions API 사용.

API 키는 openai 패키지 관례대로 환경변수 OPENAI_API_KEY에서 읽는다
(requirements.txt에 이미 openai>=1.0.0 명시). 모델명은 OPENAI_MODEL
환경변수로 오버라이드 가능하며 기본값은 "gpt-4o-mini"로 둔다 (비용/속도
균형 — CRITICAL/EMERGENCY 진입 시점에만 호출되므로 빈도는 낮지만 그래도
저비용 모델을 기본으로 택함).

analyze()가 실패(네트워크 오류·JSON 파싱 실패 등)해도 예외를 밖으로
던지지 않고 attack_type="Unknown"인 안전한 ThreatAnalysis를 반환한다.
AI 분석은 어디까지나 참고 정보이고, 여기서 예외가 나서 RiskEngine·
ResponseEngine 등 상위 파이프라인을 막으면 안 되기 때문이다.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from openai import OpenAI

from app.blue_agent.ai.prompts import SYSTEM_PROMPT
from app.blue_agent.ai.provider import LLMProvider, ThreatAnalysis
from app.blue_agent.models.events import SecurityEvent
from app.blue_agent.rules.base import RuleResult

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions 기반 LLMProvider 구현체."""

    def __init__(self, model: str | None = None, client: OpenAI | None = None) -> None:
        self._model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        if client is not None:
            self._client = client
        else:
            try:
                self._client = OpenAI()
            except Exception:
                # OPENAI_API_KEY 미설정 등으로 클라이언트 생성 자체가 실패해도
                # 서버 기동을 막으면 안 된다 — analyze()에서 안전하게 폴백한다.
                self._client = None

    def analyze(self, events: list[SecurityEvent], rule_results: list[RuleResult]) -> ThreatAnalysis:
        drone_id = rule_results[0].drone_id if rule_results else (events[0].drone_id if events else "unknown")
        if self._client is None:
            return ThreatAnalysis(
                drone_id=drone_id,
                summary="AI 분석 비활성화: OPENAI_API_KEY 미설정",
                attack_type="Unknown",
                confidence=0.0,
                recommended_action="AI 분석을 사용할 수 없음 — 규칙 기반 탐지 결과만 참고할 것",
            )
        try:
            payload = {
                "events": [asdict(event) for event in events],
                "rule_results": [asdict(result) for result in rule_results],
            }
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(response.choices[0].message.content)
            return ThreatAnalysis(
                drone_id=drone_id,
                summary=str(parsed["summary"]),
                attack_type=str(parsed["attack_type"]),
                confidence=float(parsed["confidence"]),
                recommended_action=str(parsed["recommended_action"]),
            )
        except Exception as exc:  # noqa: BLE001 — AI 실패가 상위 파이프라인을 막으면 안 됨
            return ThreatAnalysis(
                drone_id=drone_id,
                summary=f"AI 분석 실패: {exc}",
                attack_type="Unknown",
                confidence=0.0,
                recommended_action="AI 분석을 사용할 수 없음 — 규칙 기반 탐지 결과만 참고할 것",
            )
