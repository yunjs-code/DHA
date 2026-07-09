"""packet_replay — 동일 발신자(sysid)의 MAVLink seq 재출현(재전송) 탐지.

MAVLink seq는 발신 시스템(sysid)마다 0~255를 순환하는 8비트 카운터이며,
이 카운터는 그 sysid가 보내는 모든 메시지 타입이 공유한다. ArduCopter SITL은
MAV_DATA_STREAM_ALL을 10Hz로 요청하는데 이것이 여러 스트림 그룹으로
팬아웃되어 실제 합산 메시지 속도는 훨씬 높다 — 그 결과 정상 트래픽에서도
seq는 단 1~3초 만에 256개를 다 돌아 자연스럽게 재출현한다.

따라서 "재출현 자체"가 아니라 "너무 이른(짧은 시간 내) 재출현"만 재전송
공격(캡처한 패킷을 그대로 재주입)의 신호로 본다. 이력 개수를 기준으로 삼는
방식(과거 WINDOW=250건 이내)은 seq가 여러 메시지 타입이 공유하는 카운터라는
점 때문에 신뢰할 수 없다 — 예: HEARTBEAT처럼 발생 빈도가 낮은 타입은 이력
개수를 아무리 줄여도 그 사이에 공유 카운터가 여러 번 돌아버릴 수 있다.
그래서 이력을 (seq, timestamp) 쌍으로 저장하고, REPLAY_WINDOW_SECONDS보다
오래된 항목은 검사 전에 먼저 제거한다 — 자연스러운 wraparound(추정
1~3초)보다 확실히 짧은 시간 안에 동일 seq가 다시 나타난 경우만 탐지한다.
"""
from __future__ import annotations

import time
from collections import deque

from app.blue_agent.models.events import (
    CommandEvent,
    HeartbeatEvent,
    RawPacketEvent,
    SecurityEvent,
)
from app.blue_agent.rules.base import BaseRule, RuleResult

REPLAY_WINDOW_SECONDS = 0.4
MAX_HISTORY = 500  # 메모리 안전장치용 상한 (시간 기반 판단과는 무관)


class PacketReplayRule(BaseRule):
    rule_id = "packet_replay"
    severity = "HIGH"

    def __init__(self) -> None:
        self._recent_seq: dict[str, deque[tuple[int, float]]] = {}

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, (HeartbeatEvent, CommandEvent, RawPacketEvent)):
            return None

        now = time.time()
        key = f"{event.drone_id}:{event.sysid}"
        history = self._recent_seq.setdefault(key, deque(maxlen=MAX_HISTORY))

        cutoff = now - REPLAY_WINDOW_SECONDS
        while history and history[0][1] < cutoff:
            history.popleft()

        if any(seq == event.seq for seq, _ts in history):
            return RuleResult(
                rule_id=self.rule_id,
                drone_id=event.drone_id,
                severity=self.severity,
                message=(
                    f"{event.drone_id}(sysid={event.sysid}) seq={event.seq} "
                    f"패킷이 {REPLAY_WINDOW_SECONDS}초 이내 재출현 — 패킷 재전송(replay) 의심"
                ),
                evidence={
                    "sysid": event.sysid,
                    "seq": event.seq,
                    "event_type": type(event).__name__,
                    "window_seconds": REPLAY_WINDOW_SECONDS,
                },
            )

        history.append((event.seq, now))
        return None
