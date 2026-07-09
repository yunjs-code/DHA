"""sysid_spoofing — 알려진 sysid(드론 FC, GCS) 이외의 sysid 관측 탐지.

정상 트래픽에는 두 개의 시스템 ID만 존재해야 한다:
  - 드론 FC 자신의 sysid (최초 HEARTBEAT에서 학습, 보통 1)
  - GCS/서버가 사용하는 sysid (sitl.py에서 source_system=255로 고정 전송)
그 외의 sysid가 담긴 패킷이 관측되면 공격자가 임의 시스템 ID로 패킷을
주입(스푸핑)했다고 판단한다. sysid<=0은 실제 패킷이 아닌 합성 이벤트
(예: 공격 스크립트 evidence에 sysid 필드가 없는 경우)의 기본값이므로 제외한다.

과거에는 최초 mismatch가 확정된 이후 나타나는 모든 후속 이벤트마다 매번
RuleResult를 반환했다. 이 룰은 HeartbeatEvent, CommandEvent, RawPacketEvent
세 가지 모두에 반응하기 때문에, sysid 하나가 잘못 섞이면(SITL 설정 실수,
일시적 패킷 손상 등) HEARTBEAT만으로도 초당 ~1회씩 HIGH가 영구히 누적되어
수 초 안에 EMERGENCY까지 치솟고 정상 GCS 명령까지 영구 차단되는 문제가
있었다 (duplicate_sysid.py/unsigned_packet.py와 동일한 패턴의 버그).

그래서 "이 drone_id 채널이 처음으로 mismatch 상태에 진입하는 전환 시점"만
본다: 같은 drone_id에서 동일한 mismatch가 계속 반복되는 것은 더 이상 매번
점수를 매기지 않는다.
"""
from __future__ import annotations

from app.blue_agent.models.events import (
    CommandEvent,
    HeartbeatEvent,
    RawPacketEvent,
    SecurityEvent,
)
from app.blue_agent.rules.base import BaseRule, RuleResult

GCS_SYSID = 255


class SysidSpoofingRule(BaseRule):
    rule_id = "sysid_spoofing"
    severity = "HIGH"

    def __init__(self) -> None:
        self._known_sysid: dict[str, int] = {}
        self._was_mismatch: dict[str, bool] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, (HeartbeatEvent, CommandEvent, RawPacketEvent)):
            return None

        sysid = event.sysid
        if sysid <= 0 or sysid == GCS_SYSID:
            return None

        drone_sysid = self._known_sysid.get(event.drone_id)
        if drone_sysid is None:
            if isinstance(event, HeartbeatEvent):
                self._known_sysid[event.drone_id] = sysid
            return None

        is_mismatch = sysid != drone_sysid
        was_mismatch = self._was_mismatch.get(event.drone_id, False)
        self._was_mismatch[event.drone_id] = is_mismatch

        if not is_mismatch or was_mismatch:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"알 수 없는 sysid={sysid} 패킷 관측 "
                f"(정상 FC sysid={drone_sysid}, GCS sysid={GCS_SYSID})"
            ),
            evidence={
                "sysid": sysid,
                "expected_sysid": drone_sysid,
                "event_type": type(event).__name__,
            },
        )
