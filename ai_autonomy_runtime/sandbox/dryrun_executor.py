from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.adapters.jackal.safe_command_wrapper import SafeCommandWrapper
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope


class DryRunResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    success: bool
    reason: str
    simulated_latency_ms: float
    candidate_id: str
    action_type: str
    safety_metadata: dict[str, Any] = Field(default_factory=dict)


class DryRunExecutor:
    def __init__(self, wrapper: SafeCommandWrapper | None = None) -> None:
        self.wrapper = wrapper or SafeCommandWrapper()

    def execute(self, candidate: ActionCandidate, envelope: SafetyEnvelope) -> DryRunResult:
        start = time.perf_counter()
        safety = self.wrapper.evaluate(candidate, envelope, require_physical_gate=False)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return DryRunResult(
            success=safety.accepted,
            reason="dry_run_ok" if safety.accepted else safety.reason,
            simulated_latency_ms=elapsed_ms,
            candidate_id=candidate.candidate_id,
            action_type=str(candidate.action_type),
            safety_metadata=safety.model_dump(mode="json"),
        )
