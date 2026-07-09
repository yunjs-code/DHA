"""Blue Agent 이벤트 모델 — SecurityEvent 베이스 + 하위 이벤트 dataclass.

EventEngine(Phase 1)이 mavlink.decode() 결과 dict 또는
attack_runner.emit() 메타데이터를 이 형태로 변환해 RuleEngine에 전달한다.
필드 구성은 각각의 원본 데이터 형태를 그대로 반영한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SecurityEvent:
    """모든 이벤트의 공통 베이스."""
    drone_id: str
    ts: float = field(default_factory=time.time)


@dataclass
class HeartbeatEvent(SecurityEvent):
    """msg_id 0 — HEARTBEAT."""
    armed: bool = False
    mode: str = ""
    sysid: int = 0
    seq: int = 0


@dataclass
class CommandEvent(SecurityEvent):
    """msg_id 76/77 (COMMAND_LONG/COMMAND_ACK) 또는 ATT-01 공격 메타.

    msg_name으로 COMMAND_LONG(실제 명령)과 COMMAND_ACK(드론의 응답)을 구분한다.
    ingest_attack()이 만드는 공격 시뮬레이션 이벤트는 명령 주입 성격이므로
    COMMAND_LONG으로 취급한다.
    """
    command: int = 0
    target_system: int = 0
    params: list[float] = field(default_factory=list)
    result: str | None = None
    sysid: int = 0
    seq: int = 0
    signed: bool = False
    msg_name: str = "COMMAND_LONG"


@dataclass
class GPSInjectionEvent(SecurityEvent):
    """ATT-02 GNSS 스푸핑 공격 메타 (attacks.run_gnss_spoof evidence 기반)."""
    spoof_lat: float = 0.0
    spoof_lon: float = 0.0
    offset_m: float = 0.0
    inject_count: int = 0
    ekf_alarm: bool = False


@dataclass
class TelemetryEvent(SecurityEvent):
    """msg_id 33/74 (GLOBAL_POSITION_INT/VFR_HUD) 등 상태 텔레메트리."""
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    relative_alt: float = 0.0
    groundspeed: float = 0.0
    heading: float = 0.0
    battery_pct: float = 100.0
    ekf_ok: bool = True


@dataclass
class RawPacketEvent(SecurityEvent):
    """룰이 아직 없는 그 외 모든 MAVLink 패킷 (RuleEngine의 fallback 입력)."""
    msg_id: int = -1
    msg_name: str = "UNKNOWN"
    sysid: int = 0
    compid: int = 0
    seq: int = 0
    incompat_flags: int = 0
    signed: bool = False
    direction: str = "down"
