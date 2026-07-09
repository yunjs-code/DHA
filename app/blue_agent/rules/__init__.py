"""rules 패키지 — 서브모듈에 정의된 BaseRule 구현체를 자동 스캔해 등록한다.

새 룰 파일을 이 디렉터리에 추가하고 BaseRule 하위 클래스를 정의하기만 하면
별도 등록 코드 없이 ALL_RULES에 자동으로 포함된다 (pkgutil.iter_modules로
서브모듈을 import하고, BaseRule.__subclasses__()로 구현체를 수집).
"""
from __future__ import annotations

import importlib
import pkgutil

from app.blue_agent.rules.base import BaseRule, RuleResult

for _, _module_name, _ in pkgutil.iter_modules(__path__):
    if _module_name == "base":
        continue
    importlib.import_module(f"{__name__}.{_module_name}")

ALL_RULES: list[BaseRule] = [cls() for cls in BaseRule.__subclasses__()]

__all__ = ["BaseRule", "RuleResult", "ALL_RULES"]
