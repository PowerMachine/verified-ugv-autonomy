from __future__ import annotations

import time

from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


class EvidenceVerifier:
    name = "evidence"

    def __init__(self, min_score: float = 0.5) -> None:
        self.min_score = float(min_score)

    def verify(self, artifact: AgenticArtifact) -> VerificationResult:
        start = time.perf_counter()
        score = float(artifact.metadata.get("evidence_score", 1.0))
        evidence_ids = artifact.metadata.get("evidence_ids", [])
        risk = str(artifact.risk_level)
        if score < self.min_score:
            passed = False
            reason = "evidence_score_below_threshold"
        elif risk in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value} and not evidence_ids:
            passed = False
            reason = "high_risk_artifact_missing_evidence_ids"
        else:
            passed = True
            reason = "evidence_ok"
        return VerificationResult(
            checker_name=self.name,
            passed=passed,
            reason=reason,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            metadata={"evidence_score": score, "evidence_ids": evidence_ids},
        )
