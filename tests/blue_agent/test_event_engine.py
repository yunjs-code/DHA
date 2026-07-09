"""EventEngine.ingest_packet() / ingest_attack() 단위 테스트.

mav.decode()가 반환하는 dict 형태와 attacks.py emit()의 evidence 형태를
그대로 흉내 낸 입력으로 올바른 SecurityEvent 하위 클래스가 나오는지 확인한다.
표준 라이브러리 unittest만 사용 (pytest는 requirements.txt에 없음).
"""
from __future__ import annotations

import unittest

from app.blue_agent.event.engine import EventEngine
from app.blue_agent.models.events import (
    CommandEvent,
    GPSInjectionEvent,
    HeartbeatEvent,
    RawPacketEvent,
    TelemetryEvent,
)


class TestIngestPacket(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = EventEngine()

    def test_heartbeat(self) -> None:
        parsed = {
            "msg_name": "HEARTBEAT",
            "armed": True,
            "mode": "GUIDED",
            "sysid": 1,
            "seq": 42,
        }
        event = self.engine.ingest_packet("drone-01", parsed)

        self.assertIsInstance(event, HeartbeatEvent)
        self.assertEqual(event.drone_id, "drone-01")
        self.assertTrue(event.armed)
        self.assertEqual(event.mode, "GUIDED")
        self.assertEqual(event.sysid, 1)
        self.assertEqual(event.seq, 42)

    def test_command_long(self) -> None:
        parsed = {
            "msg_name": "COMMAND_LONG",
            "command": 400,
            "target_system": 1,
            "params": [1.0, 21196.0, 0, 0, 0, 0, 0],
            "sysid": 255,
            "seq": 7,
            "signed": False,
        }
        event = self.engine.ingest_packet("drone-01", parsed)

        self.assertIsInstance(event, CommandEvent)
        self.assertEqual(event.command, 400)
        self.assertEqual(event.params, [1.0, 21196.0, 0, 0, 0, 0, 0])
        self.assertEqual(event.sysid, 255)

    def test_command_ack_uses_result_str(self) -> None:
        parsed = {
            "msg_name": "COMMAND_ACK",
            "command": 400,
            "result": 0,
            "result_str": "ACCEPTED",
        }
        event = self.engine.ingest_packet("drone-01", parsed)

        self.assertIsInstance(event, CommandEvent)
        self.assertEqual(event.result, "ACCEPTED")

    def test_telemetry_global_position_int(self) -> None:
        parsed = {
            "msg_name": "GLOBAL_POSITION_INT",
            "lat": 37.5665,
            "lon": 126.9780,
            "alt": 100.0,
            "relative_alt": 50.0,
        }
        event = self.engine.ingest_packet("drone-02", parsed)

        self.assertIsInstance(event, TelemetryEvent)
        self.assertEqual(event.lat, 37.5665)
        self.assertEqual(event.relative_alt, 50.0)

    def test_telemetry_vfr_hud_uses_hdg_fallback(self) -> None:
        parsed = {
            "msg_name": "VFR_HUD",
            "groundspeed": 5.2,
            "hdg": 270,
        }
        event = self.engine.ingest_packet("drone-02", parsed)

        self.assertIsInstance(event, TelemetryEvent)
        self.assertEqual(event.groundspeed, 5.2)
        self.assertEqual(event.heading, 270)

    def test_unknown_msg_falls_back_to_raw_packet(self) -> None:
        parsed = {
            "msg_name": "EKF_STATUS_REPORT",
            "msg_id": 193,
            "sysid": 1,
            "compid": 1,
            "seq": 3,
        }
        event = self.engine.ingest_packet("drone-03", parsed, direction="up")

        self.assertIsInstance(event, RawPacketEvent)
        self.assertEqual(event.msg_id, 193)
        self.assertEqual(event.msg_name, "EKF_STATUS_REPORT")
        self.assertEqual(event.direction, "up")


class TestIngestAttack(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = EventEngine()

    def test_att01_command_injection_becomes_command_event(self) -> None:
        evidence = {
            "success": True,
            "cmd": "ARM",
            "ack_result": "ACCEPTED",
            "armed_before": False,
            "armed_after": True,
        }
        event = self.engine.ingest_attack("drone-01", "att01_drone-01", evidence)

        self.assertIsInstance(event, CommandEvent)
        self.assertEqual(event.result, "ACCEPTED")

    def test_att02_gps_spoof_becomes_gps_injection_event(self) -> None:
        evidence = {
            "spoof_lat": 38.0,
            "spoof_lon": 127.0,
            "offset_m": 500.0,
            "inject_count": 12,
            "ekf_alarm": True,
        }
        event = self.engine.ingest_attack("drone-01", "att02_drone-01", evidence)

        self.assertIsInstance(event, GPSInjectionEvent)
        self.assertEqual(event.spoof_lat, 38.0)
        self.assertEqual(event.offset_m, 500.0)
        self.assertEqual(event.inject_count, 12)
        self.assertTrue(event.ekf_alarm)

    def test_att03_blackout_becomes_command_event_using_mode_after(self) -> None:
        evidence = {
            "success": True,
            "mode_before": "GUIDED",
            "mode_after": "RTL",
            "rtl_elapsed_s": 12.3,
        }
        event = self.engine.ingest_attack("drone-01", "att03_drone-01", evidence)

        self.assertIsInstance(event, CommandEvent)
        self.assertEqual(event.result, "RTL")


if __name__ == "__main__":
    unittest.main()
