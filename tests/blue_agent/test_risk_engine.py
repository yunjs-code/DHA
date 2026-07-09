"""RiskEngine(app/blue_agent/risk/engine.py) 단위 테스트.

실제 ALL_RULES는 baseline 학습형이 섞여 있어 결과가 호출 순서에 따라
흔들리므로, 여기서는 항상 고정된 RuleResult를 돌려주는 가짜 룰을 주입해
RiskEngine 자체의 집계 로직(점수 합산·등급 산출·30초 윈도우 만료)만
검증한다. 표준 라이브러리 unittest만 사용 (pytest는 requirements.txt에 없음).
"""
from __future__ import annotations

import unittest

from app.blue_agent.models.events import HeartbeatEvent
from app.blue_agent.risk.config import WINDOW_SECONDS
from app.blue_agent.risk.engine import RiskAssessment, RiskEngine
from app.blue_agent.rules.base import BaseRule, RuleResult


def hb(drone_id: str = "drone-01") -> HeartbeatEvent:
    return HeartbeatEvent(drone_id=drone_id, armed=True, mode="GUIDED")


class FixedRule(BaseRule):
    """호출될 때마다 고정된 severity의 RuleResult를 반환하는 가짜 룰."""

    def __init__(self, rule_id: str, severity: str) -> None:
        self.rule_id = rule_id
        self.severity = severity

    def evaluate(self, event) -> RuleResult | None:
        return RuleResult(rule_id=self.rule_id, drone_id=event.drone_id, severity=self.severity, message="fixed")


class SilentRule(BaseRule):
    """항상 None을 반환하는 가짜 룰 (반응 없음 경로 확인용)."""

    rule_id = "silent"
    severity = "LOW"

    def evaluate(self, event) -> RuleResult | None:
        return None


class TestRiskEngineScoring(unittest.TestCase):
    def test_no_rule_triggers_returns_none(self) -> None:
        engine = RiskEngine(rules=[SilentRule()])
        self.assertIsNone(engine.process_event(hb()))

    def test_single_low_severity_stays_safe(self) -> None:
        # LOW(1.0) * command_flood weight(1.0) = 1.0 < WARNING(10.0)
        engine = RiskEngine(rules=[FixedRule("command_flood", "LOW")])
        result = engine.process_event(hb())
        self.assertIsInstance(result, RiskAssessment)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.level, "SAFE")

    def test_repeated_medium_severity_crosses_warning(self) -> None:
        # MEDIUM(3.0) * sequence_anomaly weight(0.8) = 2.4/회. 5회 = 12.0 >= WARNING(10.0)
        engine = RiskEngine(rules=[FixedRule("sequence_anomaly", "MEDIUM")])
        result = None
        for _ in range(5):
            result = engine.process_event(hb())
        self.assertAlmostEqual(result.score, 12.0)
        self.assertEqual(result.level, "WARNING")

    def test_critical_severity_flight_termination_reaches_emergency(self) -> None:
        # CRITICAL(15.0) * flight_termination weight(1.5) = 22.5/회. 3회 = 67.5 >= EMERGENCY(50.0)
        engine = RiskEngine(rules=[FixedRule("flight_termination", "CRITICAL")])
        result = None
        for _ in range(3):
            result = engine.process_event(hb())
        self.assertAlmostEqual(result.score, 67.5)
        self.assertEqual(result.level, "EMERGENCY")

    def test_multiple_rules_triggering_same_event_are_all_recorded(self) -> None:
        engine = RiskEngine(rules=[FixedRule("command_flood", "LOW"), FixedRule("rtl_abuse", "HIGH")])
        result = engine.process_event(hb())
        self.assertEqual(len(result.triggered), 2)
        # LOW*1.0 + HIGH(7.0)*rtl_abuse weight(1.1) = 1.0 + 7.7 = 8.7
        self.assertAlmostEqual(result.score, 8.7)

    def test_scores_are_isolated_per_drone(self) -> None:
        engine = RiskEngine(rules=[FixedRule("flight_termination", "CRITICAL")])
        engine.process_event(hb(drone_id="drone-01"))
        self.assertEqual(engine.current_assessment("drone-02").score, 0.0)
        self.assertEqual(engine.current_assessment("drone-02").level, "SAFE")


class TestRiskEngineWindowEviction(unittest.TestCase):
    def test_current_assessment_evicts_entries_older_than_window(self) -> None:
        engine = RiskEngine(rules=[])
        old_result = RuleResult(rule_id="flight_termination", drone_id="drone-01", severity="CRITICAL", message="old")
        old_result.ts -= WINDOW_SECONDS + 1  # 윈도우 밖으로 밀어냄
        engine.record_results("drone-01", [old_result])

        assessment = engine.current_assessment("drone-01")
        self.assertEqual(assessment.score, 0.0)
        self.assertEqual(assessment.level, "SAFE")

    def test_entry_within_window_is_still_counted(self) -> None:
        engine = RiskEngine(rules=[])
        recent_result = RuleResult(rule_id="flight_termination", drone_id="drone-01", severity="CRITICAL", message="recent")
        recent_result.ts -= WINDOW_SECONDS - 5  # 아직 윈도우 안

        assessment = engine.record_results("drone-01", [recent_result])
        self.assertGreater(assessment.score, 0.0)
        self.assertEqual(engine.current_assessment("drone-01").score, assessment.score)


if __name__ == "__main__":
    unittest.main()
