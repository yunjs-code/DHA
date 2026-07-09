"""OpenAIProvider 단위 테스트.

OPENAI_API_KEY가 없어 OpenAI() 생성자가 실패하는 환경에서도
OpenAIProvider() 생성과 analyze() 호출이 예외 없이 안전한
ThreatAnalysis(attack_type="Unknown")를 반환하는지 검증한다.
서버 기동 시 이 경로가 예외를 던지면 app/main.py의 import가
전부 실패해 /gcs, /attacker 등 기존 엔드포인트까지 죽는다.
"""
from __future__ import annotations

import unittest

from app.blue_agent.ai.openai_provider import OpenAIProvider


class TestOpenAIProviderMissingCredentials(unittest.TestCase):
    def test_init_does_not_raise_when_client_construction_fails(self) -> None:
        provider = OpenAIProvider(client=None)
        # 실제 OPENAI_API_KEY가 설정된 환경일 수도 있으므로 client가 None인지는
        # 강제하지 않고, 생성자가 예외 없이 끝나는지만 확인한다.
        self.assertIsInstance(provider, OpenAIProvider)

    def test_analyze_returns_safe_fallback_when_client_unavailable(self) -> None:
        provider = OpenAIProvider(client=None)
        provider._client = None  # 자격 증명 미설정 상황을 강제로 재현

        result = provider.analyze(events=[], rule_results=[])

        self.assertEqual(result.attack_type, "Unknown")
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.drone_id, "unknown")


if __name__ == "__main__":
    unittest.main()
