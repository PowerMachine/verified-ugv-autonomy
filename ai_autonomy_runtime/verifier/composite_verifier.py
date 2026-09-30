from __future__ import annotations

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope
from ai_autonomy_runtime.schemas.verification_result import CompositeVerificationReport
from ai_autonomy_runtime.verifier.evidence_verifier import EvidenceVerifier
from ai_autonomy_runtime.verifier.permission_verifier import PermissionVerifier
from ai_autonomy_runtime.verifier.safety_verifier import SafetyVerifier
from ai_autonomy_runtime.verifier.schema_verifier import SchemaVerifier
from ai_autonomy_runtime.verifier.slo_verifier import SLOVerifier


class CompositeVerifier:
    def __init__(self) -> None:
        self.schema = SchemaVerifier()
        self.evidence = EvidenceVerifier()
        self.permission = PermissionVerifier()
        self.slo = SLOVerifier()
        self.safety = SafetyVerifier()

    def verify_action_artifact(
        self,
        candidate: ActionCandidate,
        artifact: AgenticArtifact,
        envelope: SafetyEnvelope,
        require_physical_gate: bool = True,
    ) -> CompositeVerificationReport:
        results = [
            self.schema.verify(candidate, ActionCandidate),
            self.schema.verify(artifact, AgenticArtifact),
            self.evidence.verify(artifact),
            self.permission.verify(artifact, envelope),
            self.slo.verify(candidate),
            self.safety.verify(candidate, envelope, require_physical_gate=require_physical_gate),
        ]
        return CompositeVerificationReport(results=results)
