"""dashboard_events.build_detection_message 단위 테스트.

RiskAssessment를 /ws/blue_agent용 "detection" 메시지로 바꿀 때 rule_id별
MITRE 매핑이 올바르게 붙는지, triggered가 비어 있으면 rules도 빈 리스트가
되는지 검증한다.
"""
from __future__ import annotations

import unittest

from app.blue_agent.risk.engine import RiskAssessment
from app.blue_agent.rules import RuleResult
from app.blue_agent.services.dashboard_events import build_detection_message


class TestBuildDetectionMessage(unittest.TestCase):
    def test_basic_shape(self) -> None:
        result = RuleResult(
            rule_id="gps_injection",
            drone_id="drone-01",
            severity="HIGH",
            message="GPS 좌표 급변",
            ts=123.0,
        )
        assessment = RiskAssessment(
            drone_id="drone-01", level="CRITICAL", score=27.3, triggered=[result]
        )

        msg = build_detection_message(assessment)

        self.assertEqual(msg["type"], "detection")
        self.assertEqual(msg["drone_id"], "drone-01")
        self.assertEqual(msg["level"], "CRITICAL")
        self.assertEqual(msg["score"], 27.3)
        self.assertEqual(len(msg["rules"]), 1)
        rule_entry = msg["rules"][0]
        self.assertEqual(rule_entry["rule_id"], "gps_injection")
        self.assertEqual(rule_entry["severity"], "HIGH")
        self.assertEqual(rule_entry["message"], "GPS 좌표 급변")
        self.assertEqual(rule_entry["ts"], 123.0)
        self.assertEqual(rule_entry["mitre"]["attack"], "T1565 - Data Manipulation")

    def test_no_triggered_rules_yields_empty_list(self) -> None:
        assessment = RiskAssessment(drone_id="drone-02", level="SAFE", score=0.0, triggered=[])
        msg = build_detection_message(assessment)
        self.assertEqual(msg["rules"], [])


if __name__ == "__main__":
    unittest.main()
