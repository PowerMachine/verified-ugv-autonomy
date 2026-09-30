from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import Severity, make_id, utc_now


class VerificationResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    result_id: str = Field(default_factory=lambda: make_id("verify"))
    checker_name: str
    passed: bool
    reason: str = "ok"
    severity: Severity = Severity.INFO
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class CompositeVerificationReport(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    report_id: str = Field(default_factory=lambda: make_id("verify_report"))
    results: list[VerificationResult] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utc_now)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def passed_checks(self) -> list[str]:
        return [result.checker_name for result in self.results if result.passed]

    @property
    def failed_checks(self) -> list[str]:
        return [result.checker_name for result in self.results if not result.passed]
