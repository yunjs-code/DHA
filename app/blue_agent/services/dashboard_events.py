"""RiskAssessment → /ws/blue_agent 브로드캐스트 메시지 변환.

_broadcast_loop()은 이벤트마다 RiskAssessment를 계산하지만 지금까지는
텔레메트리만 blue_mgr에 전달했다. 대시보드(Phase 7)의 Current Attack /
Timeline / Risk Score / Active Rules / MITRE 매핑 패널은 이 함수가 만드는
"detection" 메시지를 데이터 소스로 쓴다. 직렬화 로직을 여기 새 파일에 두고
main.py에는 호출 한 줄만 추가해 "기존 파일은 연결 지점만" 규칙을 지킨다.
"""
from __future__ import annotations

from app.blue_agent.risk.engine import RiskAssessment
from app.blue_agent.services.mitre_mapper import mapping_for


def build_detection_message(assessment: RiskAssessment) -> dict:
    return {
        "type":     "detection",
        "drone_id": assessment.drone_id,
        "level":    assessment.level,
        "score":    assessment.score,
        "rules": [
            {
                "rule_id":  result.rule_id,
                "severity": result.severity,
                "message":  result.message,
                "ts":       result.ts,
                "mitre":    vars(mapping_for(result.rule_id)),
            }
            for result in assessment.triggered
        ],
    }
