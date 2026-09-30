from __future__ import annotations

import time

from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


class PermissionVerifier:
    name = "permission"

    def verify(self, artifact: AgenticArtifact, envelope: SafetyEnvelope) -> VerificationResult:
        start = time.perf_counter()
        if artifact.requires_physical_execution and envelope.read_only:
            passed = False
            reason = "read_only_mode_blocks_physical_execution"
        elif artifact.requires_physical_execution and not envelope.physical_execution_enabled:
            passed = False
            reason = "physical_execution_disabled"
        else:
            passed = True
            reason = "permission_ok"
        return VerificationResult(
            checker_name=self.name,
            passed=passed,
            reason=reason,
            latency_ms=(time.perf_counter() - start) * 1000.0,
        )
