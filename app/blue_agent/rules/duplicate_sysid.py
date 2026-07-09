"""duplicate_sysid — 서로 다른 drone_id 채널에서 동일 sysid의 HEARTBEAT 관측 탐지.

정상 상태에서는 sysid가 드론(FC)마다 고유해야 한다. 서로 다른 drone_id
채널(각각 별도의 SITL TCP 연결)에서 동일한 sysid를 자처하는 HEARTBEAT가
나타나면, 공격자가 다른 드론의 시스템 ID를 사칭(rogue MAVLink 소스)하고
있다고 판단한다.

과거에는 충돌이 확정된 (sysid, drone_id) 조합에 대해 이후 나타나는 모든
HEARTBEAT마다 매번 RuleResult를 반환했다. sysid 충돌은 SITL 설정(예: 여러
인스턴스가 SYSID_THISMAV를 지정하지 않아 전부 기본값 1을 사용) 때문에도
발생할 수 있는데, 이 경우 초당 ~1회씩 영구히 HIGH가 누적되어 30초 슬라이딩
윈도우 총점이 EMERGENCY 임계값을 훨씬 초과해 정상 GCS 명령까지 영구
차단되는 문제가 있었다 (unsigned_packet.py와 동일한 패턴의 버그).

그래서 "이 drone_id 채널이 처음으로 충돌 상태에 진입하는 전환 시점"만
본다: 같은 drone_id에서 동일한 충돌이 계속 반복되는 것은 더 이상 매번
점수를 매기지 않는다.
"""
from __future__ import annotations

from app.blue_agent.models.events import HeartbeatEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult


class DuplicateSysidRule(BaseRule):
    rule_id = "duplicate_sysid"
    severity = "HIGH"

    def __init__(self) -> None:
        self._sysid_owner: dict[int, str] = {}
        self._was_duplicate: dict[str, bool] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, HeartbeatEvent):
            return None
        if event.sysid <= 0:
            return None

        owner = self._sysid_owner.setdefault(event.sysid, event.drone_id)

        is_duplicate = owner != event.drone_id
        was_duplicate = self._was_duplicate.get(event.drone_id, False)
        self._was_duplicate[event.drone_id] = is_duplicate

        if not is_duplicate or was_duplicate:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"sysid={event.sysid} 중복 관측: 이미 {owner}가 사용 중인데 "
                f"{event.drone_id}에서도 동일 sysid의 HEARTBEAT 발생"
            ),
            evidence={
                "sysid": event.sysid,
                "original_owner": owner,
                "duplicate_source": event.drone_id,
            },
        )
