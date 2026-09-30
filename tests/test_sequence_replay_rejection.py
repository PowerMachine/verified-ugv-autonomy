from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.executor_safety import (
    ExecutorSafetyConfig,
    evaluate_verified_command,
    last_sequence_for_command,
    load_executor_state,
    save_executor_state,
)
from tests.verified_command_helpers import make_verified_command


def test_replayed_sequence_id_is_rejected() -> None:
    command = make_verified_command(sequence_id=7)
    evaluation = evaluate_verified_command(
        command,
        ExecutorSafetyConfig(),
        last_sequence_id=7,
        now_ms=1200,
        executor_armed=True,
    )

    assert not evaluation.accepted
    assert "sequence_not_replayed" in {check.check for check in evaluation.checks if not check.passed}


def test_sequence_state_persists_last_sequence_by_robot(tmp_path) -> None:
    state_path = tmp_path / "executor_state.json"
    save_executor_state(state_path, make_verified_command(sequence_id=9))
    replay = make_verified_command(command_id="cmd_2", sequence_id=9)

    state = load_executor_state(state_path)
    evaluation = evaluate_verified_command(
        replay,
        ExecutorSafetyConfig(),
        last_sequence_id=last_sequence_for_command(state, replay),
        now_ms=1200,
        executor_armed=True,
    )

    assert not evaluation.accepted
    assert "sequence_not_replayed" in {check.check for check in evaluation.checks if not check.passed}
