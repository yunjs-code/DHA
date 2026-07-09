"""sequence_anomaly — 동일 발신자(sysid)의 MAVLink seq 비정상 점프 탐지.

정상 상태에서 seq는 발신 시스템(sysid)마다 매 패킷 +1씩 증가하다가
255에서 0으로 순환한다. 무선 링크 특성상 약간의 패킷 유실은 정상이므로
직전 seq 대비 진행폭(mod 256)이 GAP_MAX 이내면 허용한다. 이 범위를
벗어나는 큰 폭의 전진(대량 유실/세션 재시작)이나, mod 연산상 큰 전진으로
보이는 후진(예: sysid는 같은데 실제로는 다른 발신원이 끼어들어 seq가
거꾸로 감) 모두 diff가 GAP_MAX를 초과하는 형태로 나타나므로 하나의
임계치로 함께 잡아낸다. sysid_spoofing/duplicate_sysid는 sysid 자체가
바뀌거나 충돌할 때만 탐지하므로, 공격자가 sysid를 그대로 사칭하면서
패킷을 끼워 넣는 경우는 이 룰이 보완한다.
"""
from __future__ import annotations

from app.blue_agent.models.events import (
    CommandEvent,
    HeartbeatEvent,
    RawPacketEvent,
    SecurityEvent,
)
from app.blue_agent.rules.base import BaseRule, RuleResult

GAP_MAX = 20


class SequenceAnomalyRule(BaseRule):
    rule_id = "sequence_anomaly"
    severity = "MEDIUM"

    def __init__(self) -> None:
        self._last_seq: dict[str, int] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, (HeartbeatEvent, CommandEvent, RawPacketEvent)):
            return None

        key = f"{event.drone_id}:{event.sysid}"
        last_seq = self._last_seq.get(key)
        self._last_seq[key] = event.seq

        if last_seq is None:
            return None

        diff = (event.seq - last_seq) % 256
        if diff <= GAP_MAX:
            return None

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=self.severity,
            message=(
                f"{event.drone_id}(sysid={event.sysid}) seq {last_seq}→{event.seq} "
                f"비정상 점프(진행폭 {diff}, 허용 {GAP_MAX}) — 대량 패킷 유실 또는 "
                f"seq 흐름 개입 의심"
            ),
            evidence={
                "sysid": event.sysid,
                "prev_seq": last_seq,
                "seq": event.seq,
                "diff": diff,
                "gap_max": GAP_MAX,
                "event_type": type(event).__name__,
            },
        )
