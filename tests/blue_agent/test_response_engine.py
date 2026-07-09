"""ResponseEngine(app/blue_agent/response/engine.py) 단위 테스트.

on_assessment()의 등급별 전략 자동 선택과 _blocked 상태 갱신, 그리고
apply_manual_action()의 BLOCK/UNBLOCK/FORCE_RTL/DISCONNECT 네 조치를
검증한다. connector는 FakeConnector로 대체해 실제 SITL 연결 없이 테스트한다.
표준 라이브러리 unittest만 사용 (pytest는 requirements.txt에 없음).
"""
from __future__ import annotations

import unittest

from app.blue_agent.response.engine import ResponseEngine
from app.blue_agent.risk.engine import RiskAssessment


def assessment(drone_id: str = "drone-01", level: str = "SAFE", score: float = 0.0) -> RiskAssessment:
    return RiskAssessment(drone_id=drone_id, level=level, score=score, triggered=[])


class FakeConnector:
    """send_set_mode/stop 호출 여부만 기록하는 가짜 SITLConnector."""

    def __init__(self, set_mode_ok: bool = True) -> None:
        self.set_mode_ok = set_mode_ok
        self.set_mode_calls: list[int] = []
        self.stopped = False

    def send_set_mode(self, mode_id: int) -> bool:
        self.set_mode_calls.append(mode_id)
        return self.set_mode_ok

    def stop(self) -> None:
        self.stopped = True


class TestOnAssessment(unittest.TestCase):
    def test_safe_selects_log_and_does_not_block(self) -> None:
        engine = ResponseEngine()
        action = engine.on_assessment(assessment(level="SAFE"))
        self.assertEqual(action.strategy, "LOG")
        self.assertFalse(engine.is_blocked("drone-01"))

    def test_warning_selects_alert_and_does_not_block(self) -> None:
        engine = ResponseEngine()
        action = engine.on_assessment(assessment(level="WARNING"))
        self.assertEqual(action.strategy, "ALERT")
        self.assertFalse(engine.is_blocked("drone-01"))

    def test_critical_selects_drop_and_does_not_block(self) -> None:
        engine = ResponseEngine()
        action = engine.on_assessment(assessment(level="CRITICAL"))
        self.assertEqual(action.strategy, "DROP")
        self.assertFalse(engine.is_blocked("drone-01"))

    def test_emergency_selects_block_and_blocks_drone(self) -> None:
        engine = ResponseEngine()
        action = engine.on_assessment(assessment(level="EMERGENCY"))
        self.assertEqual(action.strategy, "BLOCK")
        self.assertTrue(engine.is_blocked("drone-01"))

    def test_is_blocked_defaults_to_false_for_unknown_drone(self) -> None:
        engine = ResponseEngine()
        self.assertFalse(engine.is_blocked("drone-99"))

    def test_recovering_from_emergency_to_safe_unblocks(self) -> None:
        engine = ResponseEngine()
        engine.on_assessment(assessment(level="EMERGENCY"))
        self.assertTrue(engine.is_blocked("drone-01"))
        engine.on_assessment(assessment(level="SAFE"))
        self.assertFalse(engine.is_blocked("drone-01"))


class TestApplyManualAction(unittest.TestCase):
    def test_block_sets_blocked_true(self) -> None:
        engine = ResponseEngine()
        result = engine.apply_manual_action("drone-01", "BLOCK")
        self.assertTrue(result.success)
        self.assertTrue(engine.is_blocked("drone-01"))

    def test_unblock_sets_blocked_false(self) -> None:
        engine = ResponseEngine()
        engine.on_assessment(assessment(level="EMERGENCY"))
        result = engine.apply_manual_action("drone-01", "UNBLOCK")
        self.assertTrue(result.success)
        self.assertFalse(engine.is_blocked("drone-01"))

    def test_force_rtl_sends_rtl_mode_with_connector(self) -> None:
        engine = ResponseEngine()
        connector = FakeConnector(set_mode_ok=True)
        result = engine.apply_manual_action("drone-01", "FORCE_RTL", connector=connector)
        self.assertTrue(result.success)
        self.assertEqual(connector.set_mode_calls, [6])

    def test_force_rtl_without_connector_fails(self) -> None:
        engine = ResponseEngine()
        result = engine.apply_manual_action("drone-01", "FORCE_RTL", connector=None)
        self.assertFalse(result.success)

    def test_force_rtl_when_connector_send_fails(self) -> None:
        engine = ResponseEngine()
        connector = FakeConnector(set_mode_ok=False)
        result = engine.apply_manual_action("drone-01", "FORCE_RTL", connector=connector)
        self.assertFalse(result.success)

    def test_disconnect_stops_connector_and_blocks(self) -> None:
        engine = ResponseEngine()
        connector = FakeConnector()
        result = engine.apply_manual_action("drone-01", "DISCONNECT", connector=connector)
        self.assertTrue(result.success)
        self.assertTrue(connector.stopped)
        self.assertTrue(engine.is_blocked("drone-01"))

    def test_disconnect_without_connector_fails(self) -> None:
        engine = ResponseEngine()
        result = engine.apply_manual_action("drone-01", "DISCONNECT", connector=None)
        self.assertFalse(result.success)

    def test_unknown_action_fails(self) -> None:
        engine = ResponseEngine()
        result = engine.apply_manual_action("drone-01", "NONSENSE")
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
