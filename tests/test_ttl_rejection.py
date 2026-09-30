from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig, evaluate_verified_command
from tests.verified_command_helpers import make_verified_command


def test_expired_command_is_rejected() -> None:
    evaluation = evaluate_verified_command(
        make_verified_command(created_at_ms=1000, expires_at_ms=1500),
        ExecutorSafetyConfig(),
        now_ms=1500,
        executor_armed=True,
    )

    assert not evaluation.accepted
    assert "ttl_not_expired" in {check.check for check in evaluation.checks if not check.passed}


def test_ttl_larger_than_config_is_rejected() -> None:
    evaluation = evaluate_verified_command(
        make_verified_command(created_at_ms=1000, expires_at_ms=2000),
        ExecutorSafetyConfig(command_ttl_ms=800),
        now_ms=1200,
        executor_armed=True,
    )

    assert not evaluation.accepted
    assert "ttl_within_config" in {check.check for check in evaluation.checks if not check.passed}
