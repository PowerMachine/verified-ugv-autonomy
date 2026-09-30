from __future__ import annotations

from ai_autonomy_runtime.core.audit_logger import AuditLogger
from ai_autonomy_runtime.core.promotion_manager import PromotionManager
from ai_autonomy_runtime.core.rollback_manager import RollbackManager
from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact
from ai_autonomy_runtime.schemas.promotion_decision import PromotionDecision
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


class AutonomyManager:
    def __init__(
        self,
        audit_logger: AuditLogger,
        promotion_manager: PromotionManager | None = None,
        rollback_manager: RollbackManager | None = None,
    ) -> None:
        self.audit_logger = audit_logger
        self.promotion_manager = promotion_manager or PromotionManager()
        self.rollback_manager = rollback_manager or RollbackManager()

    def promote(
        self,
        artifact: AgenticArtifact,
        verification_results: list[VerificationResult],
        slo_passed: bool,
        operator_armed: bool = False,
        safety_passed: bool = False,
        evidence_score: float = 1.0,
        model_confidence: float = 1.0,
    ) -> PromotionDecision:
        self.audit_logger.log_agentic_artifact(artifact)
        for result in verification_results:
            self.audit_logger.log_verification_result(result)
        decision = self.promotion_manager.decide(
            artifact=artifact,
            verification_results=verification_results,
            slo_passed=slo_passed,
            operator_armed=operator_armed,
            safety_passed=safety_passed,
            evidence_score=evidence_score,
            model_confidence=model_confidence,
            rollback_available=self.rollback_manager.available,
        )
        self.audit_logger.log_promotion_decision(decision)
        return decision
