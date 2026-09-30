"""Pydantic schemas for runtime artifacts and events."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ActionCandidate": "ai_autonomy_runtime.schemas.action_candidate",
    "ActionType": "ai_autonomy_runtime.schemas.action_candidate",
    "AgenticArtifact": "ai_autonomy_runtime.schemas.agentic_artifact",
    "ArtifactType": "ai_autonomy_runtime.schemas.agentic_artifact",
    "PromotionDecision": "ai_autonomy_runtime.schemas.promotion_decision",
    "PromotionDecisionType": "ai_autonomy_runtime.schemas.promotion_decision",
    "RuntimeEvent": "ai_autonomy_runtime.schemas.runtime_event",
    "RuntimeEventType": "ai_autonomy_runtime.schemas.runtime_event",
    "ExecutionReceipt": "ai_autonomy_runtime.schemas.execution_receipt",
    "OperatorApproval": "ai_autonomy_runtime.schemas.operator_approval",
    "RobotStateSnapshot": "ai_autonomy_runtime.schemas.robot_state_snapshot",
    "SafetyEnvelope": "ai_autonomy_runtime.schemas.safety_envelope",
    "VerificationResult": "ai_autonomy_runtime.schemas.verification_result",
    "VerifiedCommand": "ai_autonomy_runtime.schemas.verified_command",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
