"""BaseRule 하위 10종 룰의 단독 단위 테스트.

각 테스트는 ALL_RULES 싱글턴을 재사용하지 않고 Rule 클래스를 직접
새로 인스턴스화한다 — baseline 학습형(sysid_spoofing, duplicate_sysid,
unsigned_packet, unknown_mode_change)과 윈도우형(command_flood,
packet_replay, sequence_anomaly) 룰은 인스턴스 상태를 갖고 있어 테스트 간
공유하면 순서에 따라 결과가 오염되기 때문이다.
표준 라이브러리 unittest만 사용 (pytest는 requirements.txt에 없음).
"""
from __future__ import annotations

import unittest
from unittest import mock

from app.blue_agent.models.events import CommandEvent, GPSInjectionEvent, HeartbeatEvent
from app.blue_agent.rules.base import RuleResult
from app.blue_agent.rules.command_flood import CommandFloodRule
from app.blue_agent.rules.duplicate_sysid import DuplicateSysidRule
from app.blue_agent.rules.flight_termination import FlightTerminationRule
from app.blue_agent.rules.gps_injection import GpsInjectionRule
from app.blue_agent.rules.packet_replay import PacketReplayRule
from app.blue_agent.rules.rtl_abuse import RtlAbuseRule
from app.blue_agent.rules.sequence_anomaly import SequenceAnomalyRule
from app.blue_agent.rules.sysid_spoofing import SysidSpoofingRule
from app.blue_agent.rules.unknown_mode_change import UnknownModeChangeRule
from app.blue_agent.rules.unsigned_packet import UnsignedPacketRule


def hb(drone_id="drone-01", sysid=1, seq=0, mode="GUIDED", armed=True) -> HeartbeatEvent:
    return HeartbeatEvent(drone_id=drone_id, armed=armed, mode=mode, sysid=sysid, seq=seq)


def cmd(drone_id="drone-01", command=400, sysid=1, seq=0, signed=False, params=None) -> CommandEvent:
    return CommandEvent(
        drone_id=drone_id,
        command=command,
        params=params or [0, 0, 0, 0, 0, 0, 0],
        sysid=sysid,
        seq=seq,
        signed=signed,
    )


class TestSysidSpoofingRule(unittest.TestCase):
    def test_first_heartbeat_learns_baseline_no_alert(self) -> None:
        rule = SysidSpoofingRule()
        self.assertIsNone(rule.evaluate(hb(sysid=1)))

    def test_matching_sysid_after_baseline_no_alert(self) -> None:
        rule = SysidSpoofingRule()
        rule.evaluate(hb(sysid=1))
        self.assertIsNone(rule.evaluate(cmd(sysid=1)))

    def test_mismatched_sysid_after_baseline_triggers(self) -> None:
        rule = SysidSpoofingRule()
        rule.evaluate(hb(sysid=1))
        result = rule.evaluate(cmd(sysid=9))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "sysid_spoofing")
        self.assertEqual(result.severity, "HIGH")
        self.assertEqual(result.evidence["sysid"], 9)
        self.assertEqual(result.evidence["expected_sysid"], 1)

    def test_gcs_sysid_255_ignored(self) -> None:
        rule = SysidSpoofingRule()
        rule.evaluate(hb(sysid=1))
        self.assertIsNone(rule.evaluate(cmd(sysid=255)))


class TestDuplicateSysidRule(unittest.TestCase):
    def test_first_owner_no_alert(self) -> None:
        rule = DuplicateSysidRule()
        self.assertIsNone(rule.evaluate(hb(drone_id="drone-01", sysid=1)))

    def test_same_drone_reusing_sysid_no_alert(self) -> None:
        rule = DuplicateSysidRule()
        rule.evaluate(hb(drone_id="drone-01", sysid=1))
        self.assertIsNone(rule.evaluate(hb(drone_id="drone-01", sysid=1)))

    def test_different_drone_same_sysid_triggers(self) -> None:
        rule = DuplicateSysidRule()
        rule.evaluate(hb(drone_id="drone-01", sysid=1))
        result = rule.evaluate(hb(drone_id="drone-02", sysid=1))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "duplicate_sysid")
        self.assertEqual(result.evidence["original_owner"], "drone-01")
        self.assertEqual(result.evidence["duplicate_source"], "drone-02")

    def test_sustained_duplicate_does_not_flood(self) -> None:
        # SITL 설정 오류(예: 두 인스턴스가 같은 SYSID_THISMAV)로 인해 같은
        # 충돌이 매 HEARTBEAT마다(~1Hz) 계속 관측되더라도, 최초 전환 시점
        # 이후로는 더 이상 반복 채점되지 않아야 한다 (영구 EMERGENCY/차단 방지).
        rule = DuplicateSysidRule()
        rule.evaluate(hb(drone_id="drone-01", sysid=1))
        first = rule.evaluate(hb(drone_id="drone-02", sysid=1))
        self.assertIsInstance(first, RuleResult)
        for _ in range(30):
            self.assertIsNone(rule.evaluate(hb(drone_id="drone-02", sysid=1)))


class TestUnsignedPacketRule(unittest.TestCase):
    def test_no_signing_baseline_yet_no_alert(self) -> None:
        rule = UnsignedPacketRule()
        self.assertIsNone(rule.evaluate(cmd(signed=False)))

    def test_signed_event_establishes_baseline_no_alert(self) -> None:
        rule = UnsignedPacketRule()
        self.assertIsNone(rule.evaluate(cmd(signed=True)))

    def test_unsigned_after_signed_baseline_triggers(self) -> None:
        rule = UnsignedPacketRule()
        rule.evaluate(cmd(signed=True))
        result = rule.evaluate(cmd(signed=False))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "unsigned_packet")
        self.assertFalse(result.evidence["signed"])


class TestFlightTerminationRule(unittest.TestCase):
    def test_non_termination_command_no_alert(self) -> None:
        rule = FlightTerminationRule()
        self.assertIsNone(rule.evaluate(cmd(command=400)))

    def test_termination_command_triggers_critical(self) -> None:
        rule = FlightTerminationRule()
        result = rule.evaluate(cmd(command=185))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "flight_termination")
        self.assertEqual(result.severity, "CRITICAL")
        self.assertEqual(result.evidence["command"], 185)


class TestCommandFloodRule(unittest.TestCase):
    def test_five_commands_within_window_no_alert(self) -> None:
        rule = CommandFloodRule()
        results = [rule.evaluate(cmd(seq=i)) for i in range(5)]
        self.assertTrue(all(r is None for r in results))

    def test_sixth_command_within_window_triggers(self) -> None:
        rule = CommandFloodRule()
        for i in range(5):
            rule.evaluate(cmd(seq=i))
        result = rule.evaluate(cmd(seq=5))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "command_flood")
        self.assertEqual(result.severity, "MEDIUM")
        self.assertEqual(result.evidence["count"], 6)


class TestGpsInjectionRule(unittest.TestCase):
    def test_small_offset_no_alarm_no_alert(self) -> None:
        rule = GpsInjectionRule()
        event = GPSInjectionEvent(drone_id="drone-01", offset_m=1.0, ekf_alarm=False)
        self.assertIsNone(rule.evaluate(event))

    def test_large_offset_triggers_high(self) -> None:
        rule = GpsInjectionRule()
        event = GPSInjectionEvent(drone_id="drone-01", offset_m=500.0, ekf_alarm=False)
        result = rule.evaluate(event)
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "gps_injection")
        self.assertEqual(result.severity, "HIGH")

    def test_ekf_alarm_triggers_critical_even_small_offset(self) -> None:
        rule = GpsInjectionRule()
        event = GPSInjectionEvent(drone_id="drone-01", offset_m=1.0, ekf_alarm=True)
        result = rule.evaluate(event)
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.severity, "CRITICAL")


class TestPacketReplayRule(unittest.TestCase):
    def test_new_seq_no_alert(self) -> None:
        rule = PacketReplayRule()
        self.assertIsNone(rule.evaluate(hb(seq=1)))

    def test_repeated_seq_within_window_triggers(self) -> None:
        rule = PacketReplayRule()
        rule.evaluate(hb(seq=7))
        result = rule.evaluate(hb(seq=7))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "packet_replay")
        self.assertEqual(result.evidence["seq"], 7)

    def test_seq_reappearing_after_window_expires_no_alert(self) -> None:
        # 자연스러운 seq wraparound 재현: REPLAY_WINDOW_SECONDS보다 오래 지난
        # 뒤에 같은 seq가 다시 나타나면 재전송으로 보지 않아야 한다.
        rule = PacketReplayRule()
        with mock.patch("app.blue_agent.rules.packet_replay.time.time", return_value=1000.0):
            rule.evaluate(hb(seq=0))
        with mock.patch("app.blue_agent.rules.packet_replay.time.time", return_value=1001.0):
            result = rule.evaluate(hb(seq=0))
        self.assertIsNone(result)

    def test_high_volume_traffic_within_window_still_triggers(self) -> None:
        # 많은 수의 서로 다른 seq가 짧은 시간 안에 몰아쳐도(높은 합산 메시지율),
        # 실제로 같은 seq가 window 이내에 재출현하면 여전히 탐지되어야 한다.
        rule = PacketReplayRule()
        with mock.patch("app.blue_agent.rules.packet_replay.time.time", return_value=2000.0):
            for i in range(251):
                rule.evaluate(hb(seq=i % 256))
            result = rule.evaluate(hb(seq=0))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "packet_replay")


class TestSequenceAnomalyRule(unittest.TestCase):
    def test_first_event_no_baseline_no_alert(self) -> None:
        rule = SequenceAnomalyRule()
        self.assertIsNone(rule.evaluate(hb(seq=10)))

    def test_small_gap_within_allowance_no_alert(self) -> None:
        rule = SequenceAnomalyRule()
        rule.evaluate(hb(seq=10))
        self.assertIsNone(rule.evaluate(hb(seq=30)))

    def test_large_gap_triggers(self) -> None:
        rule = SequenceAnomalyRule()
        rule.evaluate(hb(seq=10))
        result = rule.evaluate(hb(seq=40))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "sequence_anomaly")
        self.assertEqual(result.evidence["diff"], 30)

    def test_wraparound_within_allowance_no_alert(self) -> None:
        rule = SequenceAnomalyRule()
        rule.evaluate(hb(seq=250))
        self.assertIsNone(rule.evaluate(hb(seq=14)))


class TestUnknownModeChangeRule(unittest.TestCase):
    def test_known_mode_no_alert(self) -> None:
        rule = UnknownModeChangeRule()
        self.assertIsNone(rule.evaluate(hb(mode="GUIDED")))

    def test_same_mode_repeated_no_alert(self) -> None:
        rule = UnknownModeChangeRule()
        rule.evaluate(hb(mode="GUIDED"))
        self.assertIsNone(rule.evaluate(hb(mode="GUIDED")))

    def test_change_to_unknown_mode_triggers(self) -> None:
        rule = UnknownModeChangeRule()
        rule.evaluate(hb(mode="GUIDED"))
        result = rule.evaluate(hb(mode="FLIP"))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "unknown_mode_change")
        self.assertEqual(result.evidence["mode"], "FLIP")
        self.assertEqual(result.evidence["prev_mode"], "GUIDED")

    def test_first_event_unknown_mode_triggers(self) -> None:
        rule = UnknownModeChangeRule()
        result = rule.evaluate(hb(mode="FLIP"))
        self.assertIsInstance(result, RuleResult)
        self.assertIsNone(result.evidence["prev_mode"])


class TestRtlAbuseRule(unittest.TestCase):
    def test_non_rtl_command_no_alert(self) -> None:
        rule = RtlAbuseRule()
        self.assertIsNone(rule.evaluate(cmd(command=400)))

    def test_rtl_command_long_triggers(self) -> None:
        rule = RtlAbuseRule()
        result = rule.evaluate(cmd(command=20))
        self.assertIsInstance(result, RuleResult)
        self.assertEqual(result.rule_id, "rtl_abuse")
        self.assertEqual(result.severity, "HIGH")
        self.assertEqual(result.evidence["command"], 20)


if __name__ == "__main__":
    unittest.main()
