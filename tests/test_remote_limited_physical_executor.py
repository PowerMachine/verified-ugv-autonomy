from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_autonomy_runtime.cli.run_remote_verified_executor_limited_physical import (
    build_remote_limited_physical_command,
    run_remote_limited_physical,
)
from ai_autonomy_runtime.adapters.jackal.physical_readiness import (
    DEFAULT_ACK_PHRASE,
    PhysicalReadinessConfig,
    evaluate_limited_physical_readiness,
)
from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from tests.verified_command_helpers import make_verified_command


def test_limited_physical_command_uses_readiness_gated_executor() -> None:
    args = argparse.Namespace(
        host="192.0.2.10",
        remote_project_dir="/home/robot/ai-autonomy-ugv",
        remote_config="configs/jackal_inverted_bench_executor.yaml",
        remote_state_file="/tmp/state.json",
    )

    remote = build_remote_limited_physical_command(args, "/tmp/readiness.json")

    assert "ai_autonomy_runtime.cli.run_verified_executor" in remote
    assert "--armed --readiness-report /tmp/readiness.json" in remote
    assert "run_ugv_teleop" not in remote
    assert "run_verified_executor_dryrun" not in remote
    assert "export PYTHONPATH=$PWD:${PYTHONPATH:-}" in remote


def test_limited_physical_cli_blocks_without_explicit_publish_ack(tmp_path: Path) -> None:
    command_path = tmp_path / "verified_command.json"
    command_path.write_text(json.dumps(make_verified_command().model_dump(mode="json")), encoding="utf-8")
    readiness_path = tmp_path / "readiness_review.json"
    review = evaluate_limited_physical_readiness(
        config=PhysicalReadinessConfig(require_inverted_bench=True),
        executor_config=ExecutorSafetyConfig(max_linear_x=0.05, max_duration_ms=700),
        remote_suite_summary={
            "suite_passed": True,
            "case_count": 8,
            "executed_any": False,
            "ros_published_any": False,
            "publish_disabled_all": True,
        },
        live_summary={"sample_count": 1, "stream_complete": True},
        operator_ack_text=DEFAULT_ACK_PHRASE,
        estop_available=True,
        safe_area_confirmed=True,
        deadman_tested=True,
        stop_policy_tested=True,
        inverted_bench_confirmed=True,
        env={"ENABLE_PHYSICAL_EXECUTION": "1"},
    )
    readiness_path.write_text(json.dumps(review.model_dump(mode="json")), encoding="utf-8")
    output = tmp_path / "limited_physical"
    args = argparse.Namespace(
        host="192.0.2.10",
        user="robot",
        remote_project_dir="/home/robot/ai-autonomy-ugv",
        identity_file=None,
        input_file=str(command_path),
        readiness_report=str(readiness_path),
        remote_config="configs/jackal_inverted_bench_executor.yaml",
        remote_state_file="/tmp/state.json",
        remote_readiness_path=None,
        output=str(output),
        ssh_connect_timeout=5,
        executor_timeout=5,
        skip_code_sync=True,
        inverted_bench_confirmed=True,
        i_understand_this_will_publish_cmd_vel=False,
    )

    summary = run_remote_limited_physical(args)

    assert summary["accepted"] is False
    assert summary["executed"] is False
    assert summary["publish_disabled"] is True
    assert summary["ros_published"] is False
    assert summary["ssh_used"] is False
    assert summary["rejected_reason"] == "explicit_cmd_vel_publish_ack_required"
