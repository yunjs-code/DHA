"""mitre_mapper(app/blue_agent/services/mitre_mapper.py) 단위 테스트.

RuleEngine이 산출하는 10종 rule_id 전부가 실제 매핑(미매핑 플레이스홀더가
아닌 값)을 갖는지, mapping_for()가 알려진 rule_id에 대해 올바른 매핑을
반환하는지, 그리고 존재하지 않는 rule_id에 대해 "미매핑" 플레이스홀더로
안전하게 폴백하는지 검증한다. 표준 라이브러리 unittest만 사용
(pytest는 requirements.txt에 없음).
"""
from __future__ import annotations

import unittest

from app.blue_agent.services.mitre_mapper import MITRE_MAPPING, mapping_for

RULE_IDS = [
    "command_flood",
    "duplicate_sysid",
    "flight_termination",
    "gps_injection",
    "packet_replay",
    "rtl_abuse",
    "sequence_anomaly",
    "sysid_spoofing",
    "unknown_mode_change",
    "unsigned_packet",
]


class TestMitreMappingCompleteness(unittest.TestCase):
    def test_all_ten_rule_ids_present(self) -> None:
        self.assertEqual(set(MITRE_MAPPING.keys()), set(RULE_IDS))

    def test_all_mappings_are_not_placeholder(self) -> None:
        for rule_id in RULE_IDS:
            mapping = MITRE_MAPPING[rule_id]
            self.assertNotEqual(mapping.attack, "미매핑")
            self.assertNotEqual(mapping.attack_ics, "미매핑")
            self.assertNotEqual(mapping.d3fend, "미매핑")


class TestMappingFor(unittest.TestCase):
    def test_known_rule_id_returns_correct_mapping(self) -> None:
        mapping = mapping_for("gps_injection")
        self.assertEqual(mapping.attack, "T1565 - Data Manipulation")
        self.assertEqual(mapping.attack_ics, "T0856 - Spoof Reporting Message")
        self.assertEqual(mapping.d3fend, "Platform Monitoring")

    def test_duplicate_sysid_uses_mutual_authentication(self) -> None:
        self.assertEqual(mapping_for("duplicate_sysid").d3fend, "Mutual Authentication")

    def test_unknown_rule_id_falls_back_to_placeholder(self) -> None:
        mapping = mapping_for("no_such_rule")
        self.assertEqual(mapping.attack, "미매핑")
        self.assertEqual(mapping.attack_ics, "미매핑")
        self.assertEqual(mapping.d3fend, "미매핑")


if __name__ == "__main__":
    unittest.main()
