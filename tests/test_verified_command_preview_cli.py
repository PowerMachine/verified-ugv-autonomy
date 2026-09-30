from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_autonomy_runtime.cli.run_verified_command_preview import run_preview_bridge


def test_verified_command_preview_creates_command_when_operator_approved(tmp_path: Path) -> None:
    args = _args(tmp_path, operator_approved=True)

    summary = run_preview_bridge(args)

    assert summary["accepted"]
    assert summary["verified_command_created"]
    assert summary["executor_dryrun_receipt"]
    assert summary["executor_dryrun_executed"] is False
    assert summary["ros_published"] is False
    assert summary["ssh_used"] is False
    command = json.loads((tmp_path / "verified_command.json").read_text(encoding="utf-8"))
    assert command["target_topic"] == "/cmd_vel"
    assert command["linear_x"] == 0.05
    assert command["operator_armed"] is True


def test_verified_command_preview_allows_limited_declared_limits(tmp_path: Path) -> None:
    args = _args(tmp_path, operator_approved=True)
    args.linear = 0.02
    args.duration_ms = 400
    args.max_linear = 0.03
    args.max_angular = 0.08

    summary = run_preview_bridge(args)

    assert summary["accepted"]
    command = json.loads((tmp_path / "verified_command.json").read_text(encoding="utf-8"))
    assert command["linear_x"] == 0.02
    assert command["duration_ms"] == 400
    assert command["max_linear_x"] == 0.03
    assert command["max_angular_z"] == 0.08


def test_verified_command_preview_rejects_missing_operator_approval(tmp_path: Path) -> None:
    args = _args(tmp_path, operator_approved=False)

    summary = run_preview_bridge(args)

    assert not summary["accepted"]
    assert not summary.get("verified_command_created", False)
    payload = json.loads((tmp_path / "verified_command.json").read_text(encoding="utf-8"))
    assert payload["created"] is False


def _args(output: Path, operator_approved: bool) -> argparse.Namespace:
    return argparse.Namespace(
        action="forward",
        linear=0.05,
        angular=0.0,
        duration_ms=700,
        output=str(output),
        operator_id="test_operator",
        operator_approved=operator_approved,
        sequence_id=1,
        target_robot="jackal",
        target_topic="/cmd_vel",
        executor_armed_preview=True,
    )
