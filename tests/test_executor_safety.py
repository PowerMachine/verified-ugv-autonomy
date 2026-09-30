from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig, evaluate_verified_command
from ai_autonomy_runtime.adapters.jackal.verified_executor import VerifiedExecutor
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand
from tests.verified_command_helpers import make_verified_command


def failed_check_names(command: VerifiedCommand, **kwargs: object) -> set[str]:
    evaluation = evaluate_verified_command(
        command,
        ExecutorSafetyConfig(),
        now_ms=1200,
        executor_armed=True,
        **kwargs,
    )
    return {check.check for check in evaluation.checks if not check.passed}


def test_executor_safety_accepts_valid_armed_command() -> None:
    evaluation = evaluate_verified_command(
        make_verified_command(),
        ExecutorSafetyConfig(),
        now_ms=1200,
        executor_armed=True,
    )

    assert evaluation.accepted
    assert evaluation.rejected_reason is None


def test_wrong_topic_is_rejected_by_allow_list() -> None:
    failed = failed_check_names(make_verified_command(target_topic="/jackal_velocity_controller/cmd_vel"))
    assert "topic_allow_list" in failed


def test_missing_operator_armed_field_is_rejected_by_executor_schema(tmp_path) -> None:
    payload = make_verified_command().model_dump(mode="json")
    payload.pop("operator_armed")
    executor = VerifiedExecutor(
        config=ExecutorSafetyConfig(),
        state_path=tmp_path / "executor_state.json",
        run_dir=tmp_path / "run",
    )

    receipt = executor.execute(payload, armed=True)

    assert not receipt.accepted
    assert not receipt.executed
    assert receipt.rejected_reason is not None
    assert "schema_validation_failed" in receipt.rejected_reason


def test_operator_armed_false_is_rejected() -> None:
    failed = failed_check_names(make_verified_command(operator_armed=False))
    assert "operator_armed" in failed


def test_missing_operator_approval_id_is_rejected() -> None:
    failed = failed_check_names(make_verified_command(approval_id=None))
    assert "operator_approval_id_present" in failed
