from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.safe_command_wrapper import SafeCommandWrapper
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope
from ai_autonomy_runtime.verifier.safety_verifier import SafetyVerifier


def test_physical_velocity_rejected_by_default_safety_envelope() -> None:
    candidate = ActionCandidate(
        action_type=ActionType.VELOCITY_CANDIDATE,
        parameters={"linear_x": 1.0, "angular_z": 1.0, "sequence_id": 1},
        risk_level=RiskLevel.MEDIUM,
        requires_physical_execution=True,
    )
    result = SafetyVerifier().verify(candidate, SafetyEnvelope(), require_physical_gate=True)
    assert not result.passed
    assert "physical_execution_enabled" in result.metadata["checks"]


def test_velocity_is_clamped_in_static_dryrun_check() -> None:
    candidate = ActionCandidate(
        action_type=ActionType.VELOCITY_CANDIDATE,
        parameters={"linear_x": 1.0, "angular_z": -1.0, "sequence_id": 1},
        risk_level=RiskLevel.MEDIUM,
        requires_physical_execution=True,
    )
    envelope = SafetyEnvelope(allowed_actions=["velocity_candidate"])
    result = SafeCommandWrapper().evaluate(candidate, envelope, require_physical_gate=False)
    assert result.accepted
    assert result.clamped_command["linear_x"] == envelope.max_linear_mps
    assert result.clamped_command["angular_z"] == -envelope.max_angular_radps
