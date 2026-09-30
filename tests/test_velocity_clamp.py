from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig, evaluate_verified_command
from tests.verified_command_helpers import make_verified_command


def test_linear_velocity_over_limit_is_rejected() -> None:
    evaluation = evaluate_verified_command(
        make_verified_command(linear_x=0.09),
        ExecutorSafetyConfig(max_linear_x=0.08),
        now_ms=1200,
        executor_armed=True,
    )

    assert not evaluation.accepted
    assert "linear_velocity_limit" in {check.check for check in evaluation.checks if not check.passed}


def test_angular_velocity_over_limit_is_rejected() -> None:
    evaluation = evaluate_verified_command(
        make_verified_command(angular_z=-0.16),
        ExecutorSafetyConfig(max_angular_z=0.15),
        now_ms=1200,
        executor_armed=True,
    )

    assert not evaluation.accepted
    assert "angular_velocity_limit" in {check.check for check in evaluation.checks if not check.passed}
