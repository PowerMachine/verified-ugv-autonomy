from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_autonomy_runtime.adapters.jackal.executor_dryrun import dry_run_verified_command
from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.cli.run_verified_executor_dryrun import run_executor_dryrun
from ai_autonomy_runtime.schemas.verified_command import current_time_ms
from tests.verified_command_helpers import make_verified_command


def test_executor_dryrun_accepts_when_executor_armed_preview() -> None:
    receipt, evaluation, command = dry_run_verified_command(
        make_verified_command(),
        config=ExecutorSafetyConfig(),
        state={},
        executor_armed_preview=True,
        now_ms=1200,
    )

    assert command is not None
    assert evaluation is not None
    assert receipt.accepted
    assert not receipt.executed
    assert receipt.publish_count == 0


def test_executor_dryrun_rejects_without_executor_armed_preview() -> None:
    receipt, evaluation, _command = dry_run_verified_command(
        make_verified_command(),
        config=ExecutorSafetyConfig(),
        state={},
        executor_armed_preview=False,
        now_ms=1200,
    )

    assert evaluation is not None
    assert not receipt.accepted
    assert "executor_cli_armed" in str(receipt.rejected_reason)
    assert not receipt.executed


def test_executor_dryrun_cli_writes_receipt(tmp_path: Path) -> None:
    command_path = tmp_path / "verified_command.json"
    now_ms = current_time_ms()
    command_path.write_text(
        json.dumps(
            make_verified_command(
                created_at_ms=now_ms,
                expires_at_ms=now_ms + 800,
            ).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    output = tmp_path / "dryrun"
    args = argparse.Namespace(
        config="configs/jackal_executor_safety.yaml",
        state_file=None,
        output=str(output),
        executor_armed_preview=True,
        refresh_time_window_preview=False,
        input_json=None,
        input_file=str(command_path),
    )

    summary = run_executor_dryrun(args)

    assert summary["accepted"]
    assert summary["executed"] is False
    assert (output / "execution_receipt.json").exists()
    assert (output / "executor_safety_evaluation.json").exists()


def test_executor_dryrun_cli_can_refresh_time_window_for_preview(tmp_path: Path) -> None:
    command_path = tmp_path / "expired_verified_command.json"
    command_path.write_text(json.dumps(make_verified_command().model_dump(mode="json")), encoding="utf-8")
    output = tmp_path / "dryrun_refresh"
    args = argparse.Namespace(
        config="configs/jackal_executor_safety.yaml",
        state_file=None,
        output=str(output),
        executor_armed_preview=True,
        refresh_time_window_preview=True,
        input_json=None,
        input_file=str(command_path),
    )

    summary = run_executor_dryrun(args)

    assert summary["accepted"]
    assert summary["time_window_refreshed_for_preview"] is True


def test_executor_dryrun_can_record_preview_state_for_replay_checks(tmp_path: Path) -> None:
    state_path = tmp_path / "dryrun_state.json"
    command = make_verified_command(sequence_id=42)

    first_receipt, _first_evaluation, _first_command = dry_run_verified_command(
        command,
        config=ExecutorSafetyConfig(),
        state_path=str(state_path),
        executor_armed_preview=True,
        record_state_preview=True,
        now_ms=1200,
    )
    second_receipt, second_evaluation, _second_command = dry_run_verified_command(
        command,
        config=ExecutorSafetyConfig(),
        state_path=str(state_path),
        executor_armed_preview=True,
        now_ms=1200,
    )

    assert first_receipt.accepted
    assert state_path.exists()
    assert not second_receipt.accepted
    assert second_evaluation is not None
    assert "sequence_not_replayed" in {check.check for check in second_evaluation.checks if not check.passed}
