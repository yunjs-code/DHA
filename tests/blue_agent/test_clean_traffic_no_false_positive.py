"""클린 스타트업 트래픽 회귀 테스트 (공격자 활동 전혀 없음).

과거 버그: 서버 기동 직후 정상 GCS 사용만으로도
- sysid_spoofing이 매 HEARTBEAT마다 재발화 (전환 게이트 없음)
- command_flood가 COMMAND_LONG과 COMMAND_ACK를 함께 카운트
해서 위험도가 EMERGENCY까지 치솟아 정상 명령이 차단됐다.

test_risk_engine.py는 고정 결과를 반환하는 가짜 룰로 RiskEngine의 집계
로직만 검증하므로, 이 파일은 실제 ALL_RULES 전체를 붙여 "클린 트래픽에서
어떤 룰도 발화하지 않는다"는 회귀 자체를 검증한다. 표준 라이브러리
unittest만 사용 (pytest는 requirements.txt에 없음).
"""
from __future__ import annotations

import unittest

from app.blue_agent.event.engine import EventEngine
from app.blue_agent.risk.engine import RiskEngine

DRONES = {"drone-01": 1, "drone-02": 2, "drone-03": 3}
GCS_SYSID = 255
LEVEL_ORDER = ["SAFE", "WARNING", "CRITICAL", "EMERGENCY"]
ROUNDS = 20


class TestCleanTrafficNoFalsePositive(unittest.TestCase):
    def setUp(self) -> None:
        self.event_engine = EventEngine()
        self.risk_engine = RiskEngine()  # ALL_RULES 기본값 (프로덕션과 동일한 룰 셋)
        self._seq_counters: dict[tuple[str, int], int] = {}
        self.worst_level = "SAFE"
        self.fired: list = []

    def _next_seq(self, drone_id: str, sysid: int) -> int:
        key = (drone_id, sysid)
        self._seq_counters[key] = self._seq_counters.get(key, 0) + 1
        return self._seq_counters[key] % 256

    def _feed(self, drone_id: str, parsed: dict, direction: str = "down") -> None:
        event = self.event_engine.ingest_packet(drone_id, parsed, direction=direction)
        assessment = self.risk_engine.process_event(event)
        if assessment is None:
            return
        if LEVEL_ORDER.index(assessment.level) > LEVEL_ORDER.index(self.worst_level):
            self.worst_level = assessment.level
        self.fired.extend(assessment.triggered)

    def test_clean_multi_drone_startup_stays_safe(self) -> None:
        # 각 드론 최초 HEARTBEAT - sysid_spoofing이 FC sysid를 학습하는 시점
        for drone_id, sysid in DRONES.items():
            self._feed(
                drone_id,
                {"msg_name": "HEARTBEAT", "armed": False, "mode": "STABILIZE", "sysid": sysid, "seq": self._next_seq(drone_id, sysid)},
            )

        for round_i in range(ROUNDS):
            for drone_id, sysid in DRONES.items():
                mode = "STABILIZE" if round_i == 0 else ("GUIDED" if round_i < 15 else "RTL")
                armed = round_i >= 1

                self._feed(
                    drone_id,
                    {"msg_name": "HEARTBEAT", "armed": armed, "mode": mode, "sysid": sysid, "seq": self._next_seq(drone_id, sysid)},
                    direction="down",
                )
                self._feed(
                    drone_id,
                    {"msg_name": "GLOBAL_POSITION_INT", "lat": 37.5665 + round_i * 0.0001, "lon": 126.9780, "alt": 50.0, "relative_alt": 30.0},
                    direction="down",
                )
                self._feed(
                    drone_id,
                    {"msg_name": "VFR_HUD", "groundspeed": 5.0, "heading": 90},
                    direction="down",
                )
                self._feed(
                    drone_id,
                    {"msg_name": "SYS_STATUS", "sysid": sysid, "seq": self._next_seq(drone_id, sysid), "signed": False},
                    direction="down",
                )
                self._feed(
                    drone_id,
                    {"msg_name": "EKF_STATUS_REPORT", "sysid": sysid, "seq": self._next_seq(drone_id, sysid), "signed": False},
                    direction="down",
                )

                if round_i == 1:  # ARM
                    self._feed(
                        drone_id,
                        {"msg_name": "COMMAND_LONG", "command": 400, "sysid": GCS_SYSID, "seq": self._next_seq(drone_id, GCS_SYSID), "signed": False},
                        direction="up",
                    )
                    self._feed(
                        drone_id,
                        {"msg_name": "COMMAND_ACK", "command": 400, "result_str": "ACCEPTED", "sysid": sysid, "seq": self._next_seq(drone_id, sysid), "signed": False},
                        direction="down",
                    )
                if round_i == 2:  # TAKEOFF
                    self._feed(
                        drone_id,
                        {"msg_name": "COMMAND_LONG", "command": 22, "sysid": GCS_SYSID, "seq": self._next_seq(drone_id, GCS_SYSID), "signed": False},
                        direction="up",
                    )
                    self._feed(
                        drone_id,
                        {"msg_name": "COMMAND_ACK", "command": 22, "result_str": "ACCEPTED", "sysid": sysid, "seq": self._next_seq(drone_id, sysid), "signed": False},
                        direction="down",
                    )
                if round_i == 5:  # GOTO -> SET_POSITION_TARGET_GLOBAL_INT (COMMAND_LONG 아님)
                    self._feed(
                        drone_id,
                        {"msg_name": "SET_POSITION_TARGET_GLOBAL_INT", "sysid": GCS_SYSID, "seq": self._next_seq(drone_id, GCS_SYSID), "signed": False},
                        direction="up",
                    )

        self.assertEqual(
            self.fired, [],
            f"클린 트래픽인데 룰이 발화함: {[(r.rule_id, r.severity, r.message) for r in self.fired]}",
        )
        self.assertIn(self.worst_level, ("SAFE", "WARNING"))

        for drone_id in DRONES:
            assessment = self.risk_engine.current_assessment(drone_id)
            self.assertEqual(assessment.level, "SAFE")
            self.assertEqual(assessment.score, 0.0)


if __name__ == "__main__":
    unittest.main()
