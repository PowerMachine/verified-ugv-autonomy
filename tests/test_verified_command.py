from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand


def test_verified_command_schema_accepts_velocity_primitive() -> None:
    command = VerifiedCommand(
        command_id="cmd_1",
        sequence_id=1,
        created_at_ms=1000,
        expires_at_ms=1500,
        target_robot="jackal",
        target_topic="/cmd_vel",
        command_type="velocity_primitive",
        linear_x=0.05,
        angular_z=0.0,
        duration_ms=700,
        max_linear_x=0.08,
        max_angular_z=0.15,
        requires_stop_after=True,
        operator_armed=True,
        approval_id="approval_1",
        verifier_summary={"source": "test"},
    )

    assert command.ttl_ms == 500
    assert not command.is_expired(now_ms=1200)


def test_verified_command_rejects_invalid_time_window() -> None:
    with pytest.raises(ValidationError):
        VerifiedCommand(
            command_id="cmd_1",
            sequence_id=1,
            created_at_ms=1000,
            expires_at_ms=1000,
            target_robot="jackal",
            target_topic="/cmd_vel",
            command_type="velocity_primitive",
            linear_x=0.05,
            angular_z=0.0,
            duration_ms=700,
            max_linear_x=0.08,
            max_angular_z=0.15,
            requires_stop_after=True,
            operator_armed=True,
        )
