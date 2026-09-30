from __future__ import annotations

import json

from ai_autonomy_runtime.adapters.jackal.ssh_executor_dryrun_bridge import (
    EXECUTOR_EVENT_PREFIX,
    EXECUTOR_RECEIPT_PREFIX,
    parse_executor_dryrun_protocol,
)


def test_parser_ignores_shell_noise_and_reads_prefixed_receipt() -> None:
    receipt = {
        "command_id": "vcmd_test_001",
        "accepted": True,
        "executed": False,
        "publish_disabled": True,
        "ros_published": False,
        "rejected_reason": None,
        "publish_topic": None,
        "publish_count": 0,
        "stop_published": False,
        "executor_latency_ms": 1.25,
        "cmd_vel_out_observed": None,
        "odom_observed": None,
        "started_at_ms": 1000,
        "finished_at_ms": 1001,
    }
    stdout = "\n".join(
        [
            "Warning: Permanently added host key",
            EXECUTOR_EVENT_PREFIX + json.dumps({"event_type": "dryrun_started", "severity": "info"}),
            "ROS_PACKAGE_PATH warning that should be ignored",
            EXECUTOR_RECEIPT_PREFIX + json.dumps(receipt),
        ]
    )

    parsed = parse_executor_dryrun_protocol(stdout)

    assert parsed.receipt is not None
    assert parsed.receipt.command_id == "vcmd_test_001"
    assert parsed.receipt.accepted
    assert parsed.receipt.executed is False
    assert parsed.receipt.publish_disabled
    assert parsed.receipt.ros_published is False
    assert parsed.events == [{"event_type": "dryrun_started", "severity": "info"}]
    assert parsed.malformed == []


def test_parser_records_malformed_prefixed_lines_without_failing() -> None:
    stdout = "\n".join(
        [
            EXECUTOR_EVENT_PREFIX + "{bad-json",
            EXECUTOR_RECEIPT_PREFIX + "[]",
            "plain noise",
        ]
    )

    parsed = parse_executor_dryrun_protocol(stdout)

    assert parsed.receipt is None
    assert len(parsed.malformed) == 2
