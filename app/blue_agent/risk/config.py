"""Risk Engine 설정 — 룰별 가중치와 위험도 임계값.

RiskEngine(risk/engine.py)이 RuleResult.severity를 점수로 바꿀 때
SEVERITY_SCORES를 기본값으로 쓰고, 룰마다 오탐 가능성·실제 위험도가
달라 RULE_WEIGHTS를 곱해 보정한다(예: flight_termination은 오탐 여지가
거의 없어 가중치를 올리고, sequence_anomaly는 무선 링크 특성상 흔들림이
있어 낮춘다). 값 조정은 이 파일에서만 하면 되고 engine.py는 로직을
갖지 않는다.
"""
from __future__ import annotations

SEVERITY_SCORES: dict[str, float] = {
    "LOW": 1.0,
    "MEDIUM": 3.0,
    "HIGH": 7.0,
    "CRITICAL": 15.0,
}

DEFAULT_RULE_WEIGHT = 1.0

# rule_id -> 가중치 배수. 명시되지 않은 룰은 DEFAULT_RULE_WEIGHT 적용.
RULE_WEIGHTS: dict[str, float] = {
    "command_flood": 1.0,
    "duplicate_sysid": 1.2,
    "flight_termination": 1.5,
    "gps_injection": 1.3,
    "packet_replay": 1.0,
    "rtl_abuse": 1.1,
    "sequence_anomaly": 0.8,
    "sysid_spoofing": 1.2,
    "unknown_mode_change": 1.0,
    "unsigned_packet": 0.9,
}

# 30초 슬라이딩 윈도우 내 누적 점수가 이 값 "이상"이면 해당 등급.
# (정렬 후 마지막으로 만족하는 등급을 채택 — 아래 level_for 참고)
RISK_THRESHOLDS: dict[str, float] = {
    "SAFE": 0.0,
    "WARNING": 10.0,
    "CRITICAL": 25.0,
    "EMERGENCY": 50.0,
}

WINDOW_SECONDS = 30.0


def rule_weight(rule_id: str) -> float:
    return RULE_WEIGHTS.get(rule_id, DEFAULT_RULE_WEIGHT)


def score_for(severity: str, rule_id: str) -> float:
    """severity와 rule_id로부터 이 결과 하나의 위험 점수를 계산한다."""
    return SEVERITY_SCORES.get(severity, 0.0) * rule_weight(rule_id)


def level_for(total_score: float) -> str:
    """누적 점수를 SAFE/WARNING/CRITICAL/EMERGENCY 등급으로 변환한다."""
    level = "SAFE"
    for name, threshold in sorted(RISK_THRESHOLDS.items(), key=lambda kv: kv[1]):
        if total_score >= threshold:
            level = name
    return level
