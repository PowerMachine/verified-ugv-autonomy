from __future__ import annotations

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact, ArtifactType


class ArtifactGenerator:
    def from_action_candidate(self, candidate: ActionCandidate, target_system: str = "jackal") -> AgenticArtifact:
        return AgenticArtifact(
            artifact_type=ArtifactType.ACTION_CANDIDATE,
            source_agent=candidate.source_model,
            payload=candidate.model_dump(mode="json"),
            target_system=target_system,
            risk_level=candidate.risk_level,
            requires_physical_execution=candidate.requires_physical_execution,
            requires_human_approval=False,
            metadata={"evidence_score": 1.0, "evidence_ids": ["rule_fallback"]},
        )
