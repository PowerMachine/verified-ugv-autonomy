from __future__ import annotations

from ai_autonomy_runtime.core.promotion_manager import PromotionManager
from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact, ArtifactType
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


def test_low_risk_nonphysical_candidate_limited_promote() -> None:
    artifact = AgenticArtifact(
        artifact_type=ArtifactType.REPORT,
        payload={"summary": "ok"},
        target_system="jackal",
        risk_level=RiskLevel.LOW,
    )
    decision = PromotionManager().decide(
        artifact=artifact,
        verification_results=[VerificationResult(checker_name="schema", passed=True)],
        slo_passed=True,
        safety_passed=True,
    )
    assert decision.decision == "limited_promote"


def test_physical_candidate_requires_operator_arm_after_safety_passes() -> None:
    artifact = AgenticArtifact(
        artifact_type=ArtifactType.ACTION_CANDIDATE,
        payload={"action_type": "inspect_point"},
        target_system="jackal",
        risk_level=RiskLevel.LOW,
        requires_physical_execution=True,
    )
    decision = PromotionManager().decide(
        artifact=artifact,
        verification_results=[VerificationResult(checker_name="schema", passed=True)],
        slo_passed=True,
        safety_passed=True,
        operator_armed=False,
    )
    assert decision.decision == "human_approval"
    assert decision.requires_human_approval
