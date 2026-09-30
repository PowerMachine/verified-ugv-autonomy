from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_autonomy_runtime.adapters.jackal.outcome_monitor import review_bounded_command_outcome
from ai_autonomy_runtime.cli.run_ugv_outcome_review import run_outcome_review
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt


def test_outcome_monitor_marks_matching_cmd_in_and_cmd_out_success(tmp_path: Path) -> None:
    telemetry = tmp_path / "telemetry.log"
    telemetry.write_text(
        "\n".join(
            [
                _state_line(0, cmd_in=(0.0, 0.0), cmd_out=(0.0, 0.0)),
                _state_line(1, cmd_in=(0.0, 0.04), cmd_out=(0.0, 0.0)),
                _state_line(2, cmd_in=(0.0, 0.04), cmd_out=(0.0, 0.04)),
                _state_line(3, cmd_in=(0.0, 0.0), cmd_out=(0.0, 0.0)),
            ]
        ),
        encoding="utf-8",
    )

    review = review_bounded_command_outcome(
        telemetry_log=telemetry,
        receipt=_receipt(),
        expected_linear_x=0.0,
        expected_angular_z=0.04,
        expected_duration_ms=400,
    )

    assert review.status == "success"
    assert not review.exception_required
    assert review.observed["cmd_in"]["nonzero_samples"] == 2
    assert review.observed["cmd_out"]["nonzero_samples"] == 1


def test_outcome_monitor_requires_exception_on_wrong_direction(tmp_path: Path) -> None:
    telemetry = tmp_path / "telemetry.log"
    telemetry.write_text(
        "\n".join(
            [
                _state_line(0, cmd_in=(0.0, 0.0), cmd_out=(0.0, 0.0)),
                _state_line(1, cmd_in=(0.0, -0.04), cmd_out=(0.0, -0.04)),
                _state_line(2, cmd_in=(0.0, 0.0), cmd_out=(0.0, 0.0)),
            ]
        ),
        encoding="utf-8",
    )

    review = review_bounded_command_outcome(
        telemetry_log=telemetry,
        receipt=_receipt(),
        expected_linear_x=0.0,
        expected_angular_z=0.04,
        expected_duration_ms=400,
    )

    assert review.status == "exception_required"
    assert review.exception_required
    assert "cmd_in_expected_observed" in {check.check for check in review.checks if not check.passed}


def test_outcome_monitor_can_treat_missing_cmd_out_as_partial(tmp_path: Path) -> None:
    telemetry = tmp_path / "telemetry.log"
    telemetry.write_text(
        "\n".join(
            [
                _state_line(0, cmd_in=(0.0, 0.0), cmd_out=None),
                _state_line(1, cmd_in=(0.0, 0.04), cmd_out=None),
                _state_line(2, cmd_in=(0.0, 0.0), cmd_out=None),
            ]
        ),
        encoding="utf-8",
    )

    review = review_bounded_command_outcome(
        telemetry_log=telemetry,
        receipt=_receipt(),
        expected_linear_x=0.0,
        expected_angular_z=0.04,
        expected_duration_ms=400,
        require_cmd_out=False,
    )

    assert review.status == "partial"
    assert not review.exception_required
    assert "cmd_out_expected_observed" in {check.check for check in review.checks if not check.passed}


def test_outcome_review_cli_writes_artifacts(tmp_path: Path) -> None:
    telemetry = tmp_path / "telemetry.log"
    receipt_path = tmp_path / "receipt.json"
    output = tmp_path / "outcome"
    telemetry.write_text(
        "\n".join(
            [
                _state_line(0, cmd_in=(0.0, 0.0), cmd_out=(0.0, 0.0)),
                _state_line(1, cmd_in=(0.0, 0.04), cmd_out=(0.0, 0.04)),
                _state_line(2, cmd_in=(0.0, 0.0), cmd_out=(0.0, 0.0)),
            ]
        ),
        encoding="utf-8",
    )
    receipt_path.write_text(json.dumps(_receipt().model_dump(mode="json")), encoding="utf-8")

    summary = run_outcome_review(
        argparse.Namespace(
            telemetry_log=str(telemetry),
            receipt_file=str(receipt_path),
            expected_linear=0.0,
            expected_angular=0.04,
            expected_duration_ms=400,
            linear_tolerance=0.01,
            angular_tolerance=0.02,
            zero_epsilon=1e-6,
            output=str(output),
            no_require_cmd_out=False,
            no_require_odom=False,
            no_require_feedback=False,
            no_require_stop=False,
        )
    )

    assert summary["status"] == "success"
    assert (output / "outcome_review.json").exists()
    assert (output / "outcome_timeline.json").exists()
    assert (output / "outcome_review.html").exists()
    assert (output / "summary.json").exists()
    assert "outcome_html" in summary


def _receipt() -> ExecutionReceipt:
    return ExecutionReceipt(
        command_id="cmd_turn",
        accepted=True,
        executed=True,
        publish_disabled=False,
        ros_published=True,
        rejected_reason=None,
        publish_topic="/cmd_vel",
        publish_count=4,
        stop_published=True,
        executor_latency_ms=1200.0,
        cmd_vel_out_observed=None,
        odom_observed=None,
        started_at_ms=1000,
        finished_at_ms=2200,
    )


def _state_line(
    sample_idx: int,
    *,
    cmd_in: tuple[float, float] | None,
    cmd_out: tuple[float, float] | None,
) -> str:
    payload = {
        "schema_version": "ugv_state.v1",
        "run_id": "test",
        "sample_idx": sample_idx,
        "wall_time": 1000.0 + sample_idx * 0.05,
        "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "velocity": {"linear_x": 0.0, "angular_z": 0.0},
        "cmd_in": _twist(cmd_in),
        "cmd_out": _twist(cmd_out),
        "feedback": {"left_velocity": 0.0, "right_velocity": 0.0, "left_duty": 0.0, "right_duty": 0.0},
        "status": {
            "ros_connected": True,
            "odom_available": True,
            "cmd_in_available": cmd_in is not None,
            "cmd_out_available": cmd_out is not None,
            "feedback_available": True,
            "topic_message_counts": {
                "pose": sample_idx + 1,
                "cmd_in": sample_idx + 1 if cmd_in is not None else 0,
                "cmd_out": sample_idx + 1 if cmd_out is not None else 0,
                "feedback": sample_idx + 1,
            },
        },
    }
    return "UGV_STATE_JSON " + json.dumps(payload, separators=(",", ":"))


def _twist(value: tuple[float, float] | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {"linear_x": value[0], "angular_z": value[1]}
