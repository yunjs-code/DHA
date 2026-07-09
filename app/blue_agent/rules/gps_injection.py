"""gps_injection — GNSS 스푸핑(ATT-02) 공격 이벤트의 유의미한 위치 왜곡 탐지.

GPSInjectionEvent는 attacks.run_gnss_spoof가 att02_ 접두 attack_id로 직접
report한 evidence(offset_m, ekf_alarm 등)에서만 생성된다(engine.py 참고).
따라서 이벤트 발생 자체가 이미 공격 스크립트발 신호이지만, offset_m이
아주 작은 초기 단계(드론이 아직 실질적으로 밀려나지 않은 상태)까지 전부
경보로 올리면 노이즈가 크므로 유의미한 드리프트(OFFSET_THRESHOLD_M 이상)
또는 드론 자체 EKF가 이미 이상을 감지한 경우(ekf_alarm)만 탐지한다.
EKF까지 알람이 뜬 경우는 스푸핑이 이미 항법 안전장치를 건드린 상태이므로
CRITICAL로 격상한다.
"""
from __future__ import annotations

from app.blue_agent.models.events import GPSInjectionEvent, SecurityEvent
from app.blue_agent.rules.base import BaseRule, RuleResult

OFFSET_THRESHOLD_M = 5.0


class GpsInjectionRule(BaseRule):
    rule_id = "gps_injection"
    severity = "HIGH"

    def evaluate(self, event: SecurityEvent) -> RuleResult | None:
        if not isinstance(event, GPSInjectionEvent):
            return None

        if event.offset_m < OFFSET_THRESHOLD_M and not event.ekf_alarm:
            return None

        severity = "CRITICAL" if event.ekf_alarm else self.severity

        return RuleResult(
            rule_id=self.rule_id,
            drone_id=event.drone_id,
            severity=severity,
            message=(
                f"{event.drone_id} GPS 위치 왜곡 {event.offset_m:.1f}m 관측"
                + (" (EKF 알람 발생)" if event.ekf_alarm else "")
                + f" — GNSS 스푸핑 의심 (주입 {event.inject_count}회)"
            ),
            evidence={
                "offset_m": event.offset_m,
                "inject_count": event.inject_count,
                "ekf_alarm": event.ekf_alarm,
                "spoof_lat": event.spoof_lat,
                "spoof_lon": event.spoof_lon,
            },
        )
