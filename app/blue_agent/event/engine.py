"""EventEngine — raw MAVLink dict / attack 메타를 SecurityEvent로 변환.

두 가지 입력 경로가 있다:
- ingest_packet(): app/main.py `_broadcast_loop()`의 mav.decode() 결과
- ingest_attack(): app/attacks.py `AttackRunner.emit()`의 공격 메타데이터

두 경로 모두 변환된 SecurityEvent를 risk_engine.process_event() ->
response_engine.on_assessment()로 전달한다 (ingest_packet은 app/main.py에서,
ingest_attack은 app/attacks.py의 AttackRunner.emit()에서 각각 호출).
"""
from __future__ import annotations

import logging

from app.blue_agent.models.events import (
    CommandEvent,
    GPSInjectionEvent,
    HeartbeatEvent,
    RawPacketEvent,
    SecurityEvent,
    TelemetryEvent,
)

log = logging.getLogger(__name__)

_TELEMETRY_MSGS = {"GLOBAL_POSITION_INT", "VFR_HUD"}


class EventEngine:
    """raw dict / attack 메타 → SecurityEvent 변환기."""

    def ingest_packet(self, drone_id: str, parsed: dict, direction: str = "down") -> SecurityEvent:
        msg_name = parsed.get("msg_name", "UNKNOWN")

        if msg_name == "HEARTBEAT":
            event: SecurityEvent = HeartbeatEvent(
                drone_id=drone_id,
                armed=parsed.get("armed", False),
                mode=parsed.get("mode", ""),
                sysid=parsed.get("sysid", 0),
                seq=parsed.get("seq", 0),
            )
        elif msg_name in ("COMMAND_LONG", "COMMAND_ACK"):
            event = CommandEvent(
                drone_id=drone_id,
                command=parsed.get("command", 0),
                target_system=parsed.get("target_system", 0),
                params=parsed.get("params", []),
                result=parsed.get("result_str", parsed.get("result")),
                sysid=parsed.get("sysid", 0),
                seq=parsed.get("seq", 0),
                signed=parsed.get("signed", False),
                msg_name=msg_name,
            )
        elif msg_name in _TELEMETRY_MSGS:
            event = TelemetryEvent(
                drone_id=drone_id,
                lat=parsed.get("lat", 0.0),
                lon=parsed.get("lon", 0.0),
                alt=parsed.get("alt", 0.0),
                relative_alt=parsed.get("relative_alt", 0.0),
                groundspeed=parsed.get("groundspeed", 0.0),
                heading=parsed.get("heading", parsed.get("hdg", 0.0)),
                battery_pct=parsed.get("battery_pct", 100.0),
                ekf_ok=parsed.get("ekf_ok", True),
            )
        else:
            event = RawPacketEvent(
                drone_id=drone_id,
                msg_id=parsed.get("msg_id", -1),
                msg_name=msg_name,
                sysid=parsed.get("sysid", 0),
                compid=parsed.get("compid", 0),
                seq=parsed.get("seq", 0),
                incompat_flags=parsed.get("incompat_flags", 0),
                signed=parsed.get("signed", False),
                direction=direction,
            )

        log.debug("ingest_packet: %s", event)
        return event

    def ingest_attack(self, drone_id: str, attack_id: str, evidence: dict) -> SecurityEvent:
        if attack_id.startswith("att02_"):
            event: SecurityEvent = GPSInjectionEvent(
                drone_id=drone_id,
                spoof_lat=evidence.get("spoof_lat", 0.0),
                spoof_lon=evidence.get("spoof_lon", 0.0),
                offset_m=evidence.get("offset_m", 0.0),
                inject_count=evidence.get("inject_count", 0),
                ekf_alarm=evidence.get("ekf_alarm", False),
            )
        else:
            # att01_ (command injection), att03_ (blackout) 및 기타 공격은
            # 공통적으로 CommandEvent로 표현 (명령/모드 조작 성격이 강함).
            event = CommandEvent(
                drone_id=drone_id,
                command=evidence.get("command", 0),
                result=evidence.get("ack_result", evidence.get("mode_after")),
                msg_name="COMMAND_LONG",
            )

        log.debug("ingest_attack: %s", event)
        return event


event_engine = EventEngine()
