from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.ssh_executor_dryrun_bridge import RemoteExecutorDryRunResult
from ai_autonomy_runtime.cli.run_remote_verified_executor_dryrun_suite import (
    build_suite_steps,
    suite_step_passed,
)
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from tests.verified_command_helpers import make_verified_command


def test_suite_steps_cover_expected_negative_cases() -> None:
    base = make_verified_command().model_dump(mode="json")

    steps = build_suite_steps(base, "suite_test")
    by_case = {(step.case_id, step.step_id): step for step in steps}

    assert ("valid", "accept") in by_case
    assert by_case[("expired_without_refresh", "reject")].refresh_time_window_preview is False
    assert by_case[("over_limit_velocity", "reject")].command["linear_x"] == 0.5
    assert by_case[("wrong_topic", "reject")].command["target_topic"] == "/jackal_velocity_controller/cmd_vel"
    assert by_case[("missing_operator_approval", "reject")].command["approval_id"] is None
    assert by_case[("missing_executor_armed", "reject")].executor_armed_preview is False
    assert by_case[("replay_sequence", "record_first")].record_dryrun_state_preview is True
    assert by_case[("replay_sequence", "record_first")].remote_state_file == by_case[
        ("replay_sequence", "replay_second")
    ].remote_state_file
    assert by_case[("replay_sequence", "replay_second")].expect_reason_contains == "sequence_not_replayed"


def test_suite_step_passed_enforces_dryrun_safety_fields() -> None:
    step = build_suite_steps(make_verified_command().model_dump(mode="json"), "suite_test")[0]
    result = RemoteExecutorDryRunResult(
        receipt=ExecutionReceipt(
            command_id="cmd_1",
            accepted=True,
            executed=False,
            publish_disabled=True,
            ros_published=False,
            rejected_reason=None,
            publish_topic=None,
            publish_count=0,
            stop_published=False,
            executor_latency_ms=1.0,
            cmd_vel_out_observed=None,
            odom_observed=None,
            started_at_ms=1000,
            finished_at_ms=1001,
        ),
        remote_command="remote",
        ssh_command=["ssh"],
        prefixed_receipt_parsed=True,
    )

    passed, reason = suite_step_passed(step, result)

    assert passed
    assert reason is None


def test_suite_step_fails_when_ros_publish_is_reported() -> None:
    step = build_suite_steps(make_verified_command().model_dump(mode="json"), "suite_test")[0]
    result = RemoteExecutorDryRunResult(
        receipt=ExecutionReceipt(
            command_id="cmd_1",
            accepted=True,
            executed=False,
            publish_disabled=True,
            ros_published=True,
            rejected_reason=None,
            publish_topic=None,
            publish_count=0,
            stop_published=False,
            executor_latency_ms=1.0,
            cmd_vel_out_observed=None,
            odom_observed=None,
            started_at_ms=1000,
            finished_at_ms=1001,
        ),
        remote_command="remote",
        ssh_command=["ssh"],
        prefixed_receipt_parsed=True,
    )

    passed, reason = suite_step_passed(step, result)

    assert not passed
    assert reason == "dry-run receipt reported ros_published=true"
