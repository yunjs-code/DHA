"""rule_id -> (MITRE ATT&CK, ATT&CK for ICS, D3FEND) 매핑 테이블.

RuleEngine이 산출하는 10종 rule_id를 대시보드(Phase 7)가 사람이 읽을 수
있는 위협 분류·방어 프레임워크 참조로 보여주기 위한 정적 테이블이다.

여러 룰이 D3FEND "Message Authentication"으로 묶이는 것은 우연이 아니라
이 프로젝트가 실제로 구현한 방어가 MAVLink v2 메시지 서명(§3.3,
scripts/defense_signing.py)이기 때문이다 — sysid_spoofing/duplicate_sysid/
unsigned_packet/packet_replay/rtl_abuse/unknown_mode_change는 모두 "발신자
신원·메시지 무결성을 신뢰할 수 없다"는 동일한 근본 문제를 서명 검증으로
막을 수 있다. 반대로 gps_injection은 GNSS 신호(센서 계층)의 값 자체가
조작되는 공격이라 메시지 서명으로는 막을 수 없어 별도로 Platform
Monitoring을 매핑했고, sequence_anomaly는 인증이 아닌 통계적 이상탐지라
Network Traffic Analysis를 매핑했다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MitreMapping:
    attack: str
    attack_ics: str
    d3fend: str


_UNKNOWN = MitreMapping(attack="미매핑", attack_ics="미매핑", d3fend="미매핑")

MITRE_MAPPING: dict[str, MitreMapping] = {
    "command_flood": MitreMapping(
        attack="T1499 - Endpoint Denial of Service",
        attack_ics="T0814 - Denial of Service",
        d3fend="Rate Limiting",
    ),
    "duplicate_sysid": MitreMapping(
        attack="T1036 - Masquerading",
        attack_ics="T0849 - Masquerading",
        d3fend="Mutual Authentication",
    ),
    "sysid_spoofing": MitreMapping(
        attack="T1036 - Masquerading",
        attack_ics="T0849 - Masquerading",
        d3fend="Message Authentication",
    ),
    "unsigned_packet": MitreMapping(
        attack="T1562.010 - Impair Defenses: Downgrade Attack",
        attack_ics="T0820 - Exploitation for Evasion",
        d3fend="Message Authentication",
    ),
    "flight_termination": MitreMapping(
        attack="T1489 - Service Stop",
        attack_ics="T0816 - Device Restart/Shutdown",
        d3fend="Execution Allowlisting",
    ),
    "gps_injection": MitreMapping(
        attack="T1565 - Data Manipulation",
        attack_ics="T0856 - Spoof Reporting Message",
        d3fend="Platform Monitoring",
    ),
    "packet_replay": MitreMapping(
        attack="T1557 - Adversary-in-the-Middle",
        attack_ics="T0830 - Man in the Middle",
        d3fend="Message Authentication",
    ),
    "sequence_anomaly": MitreMapping(
        attack="T1565 - Data Manipulation",
        attack_ics="T0830 - Man in the Middle",
        d3fend="Network Traffic Analysis",
    ),
    "rtl_abuse": MitreMapping(
        attack="T1059 - Command and Scripting Interpreter",
        attack_ics="T0855 - Unauthorized Command Message",
        d3fend="Message Authentication",
    ),
    "unknown_mode_change": MitreMapping(
        attack="T1569 - System Services",
        attack_ics="T0858 - Change Operating Mode",
        d3fend="Message Authentication",
    ),
}


def mapping_for(rule_id: str) -> MitreMapping:
    """rule_id에 대응하는 매핑을 반환한다. 없으면 미매핑 플레이스홀더."""
    return MITRE_MAPPING.get(rule_id, _UNKNOWN)
