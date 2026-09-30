from __future__ import annotations

from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand


def make_verified_command(**overrides: object) -> VerifiedCommand:
    data = {
        "command_id": "cmd_1",
        "sequence_id": 1,
        "created_at_ms": 1000,
        "expires_at_ms": 1600,
        "target_robot": "jackal",
        "target_topic": "/cmd_vel",
        "command_type": "velocity_primitive",
        "linear_x": 0.05,
        "angular_z": 0.0,
        "duration_ms": 700,
        "max_linear_x": 0.08,
        "max_angular_z": 0.15,
        "requires_stop_after": True,
        "operator_armed": True,
        "approval_id": "approval_1",
        "verifier_summary": {"source": "test"},
    }
    data.update(overrides)
    return VerifiedCommand.model_validate(data)
