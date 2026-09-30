from __future__ import annotations

import time

from ai_autonomy_runtime.adapters.jackal.safe_command_wrapper import SafeCommandWrapper
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


class SafetyVerifier:
    name = "safety"

    def __init__(self, wrapper: SafeCommandWrapper | None = None) -> None:
        self.wrapper = wrapper or SafeCommandWrapper()

    def verify(
        self,
        candidate: ActionCandidate,
        envelope: SafetyEnvelope,
        require_physical_gate: bool = True,
    ) -> VerificationResult:
        start = time.perf_counter()
        result = self.wrapper.evaluate(candidate, envelope, require_physical_gate=require_physical_gate)
        return VerificationResult(
            checker_name=self.name,
            passed=result.accepted,
            reason=result.reason,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            metadata=result.model_dump(mode="json"),
        )
