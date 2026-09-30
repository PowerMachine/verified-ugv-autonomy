from __future__ import annotations

import time

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


class SLOVerifier:
    name = "slo"

    def verify(self, candidate: ActionCandidate) -> VerificationResult:
        start = time.perf_counter()
        expired = candidate.is_expired()
        duration_ok = candidate.expected_duration_ms <= candidate.ttl_ms or candidate.expected_duration_ms == 0
        passed = not expired and duration_ok
        if expired:
            reason = "candidate_ttl_expired"
        elif not duration_ok:
            reason = "expected_duration_exceeds_ttl"
        else:
            reason = "slo_ok"
        return VerificationResult(
            checker_name=self.name,
            passed=passed,
            reason=reason,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            metadata={"ttl_ms": candidate.ttl_ms, "expected_duration_ms": candidate.expected_duration_ms},
        )
