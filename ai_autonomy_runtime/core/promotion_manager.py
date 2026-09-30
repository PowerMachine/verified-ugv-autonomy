from __future__ import annotations

from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.promotion_decision import PromotionDecision, PromotionDecisionType
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


class PromotionManager:
    def decide(
        self,
        artifact: AgenticArtifact,
        verification_results: list[VerificationResult],
        slo_passed: bool,
        operator_armed: bool = False,
        safety_passed: bool = False,
        evidence_score: float = 1.0,
        model_confidence: float = 1.0,
        rollback_available: bool = False,
    ) -> PromotionDecision:
        passed_checks = [item.checker_name for item in verification_results if item.passed]
        failed_checks = [item.checker_name for item in verification_results if not item.passed]

        if failed_checks:
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=PromotionDecisionType.REJECT,
                reason="verification_failed",
                passed_checks=passed_checks,
                failed_checks=failed_checks,
                rollback_available=rollback_available,
            )

        if not slo_passed:
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=PromotionDecisionType.REJECT,
                reason="slo_violation",
                passed_checks=passed_checks,
                failed_checks=["slo"],
                rollback_available=rollback_available,
            )

        if evidence_score < 0.5:
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=PromotionDecisionType.SUGGEST_ONLY,
                reason="missing_or_weak_evidence",
                passed_checks=passed_checks,
                failed_checks=["evidence_score"],
                rollback_available=rollback_available,
            )

        if model_confidence < 0.5:
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=PromotionDecisionType.SUGGEST_ONLY,
                reason="low_model_confidence",
                passed_checks=passed_checks,
                failed_checks=["model_confidence"],
                rollback_available=rollback_available,
            )

        risk = str(artifact.risk_level)
        if risk in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value} and artifact.requires_physical_execution:
            decision = PromotionDecisionType.HUMAN_APPROVAL if safety_passed else PromotionDecisionType.REJECT
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=decision,
                reason="high_risk_physical_action_requires_human_approval",
                passed_checks=passed_checks,
                failed_checks=[] if safety_passed else ["safety"],
                requires_human_approval=True,
                rollback_available=rollback_available,
            )

        if artifact.requires_human_approval:
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=PromotionDecisionType.HUMAN_APPROVAL,
                reason="artifact_requires_human_approval",
                passed_checks=passed_checks,
                rollback_available=rollback_available,
                requires_human_approval=True,
            )

        if artifact.requires_physical_execution:
            if not safety_passed:
                return PromotionDecision(
                    artifact_id=artifact.artifact_id,
                    decision=PromotionDecisionType.DRY_RUN,
                    reason="physical_candidate_limited_to_dry_run_until_safety_passes",
                    passed_checks=passed_checks,
                    failed_checks=["safety"],
                    rollback_available=rollback_available,
                )
            if not operator_armed:
                return PromotionDecision(
                    artifact_id=artifact.artifact_id,
                    decision=PromotionDecisionType.HUMAN_APPROVAL,
                    reason="physical_candidate_requires_operator_arm",
                    passed_checks=passed_checks,
                    requires_human_approval=True,
                    rollback_available=rollback_available,
                )
            return PromotionDecision(
                artifact_id=artifact.artifact_id,
                decision=PromotionDecisionType.EXECUTE,
                reason="physical_candidate_passed_all_gates_and_is_armed",
                passed_checks=passed_checks + ["operator_armed"],
                rollback_available=rollback_available,
            )

        return PromotionDecision(
            artifact_id=artifact.artifact_id,
            decision=PromotionDecisionType.LIMITED_PROMOTE,
            reason="low_risk_nonphysical_candidate_passed_all_gates",
            passed_checks=passed_checks,
            rollback_available=rollback_available,
        )
