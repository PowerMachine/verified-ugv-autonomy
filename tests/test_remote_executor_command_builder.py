from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.ssh_executor_dryrun_bridge import (
    RemoteExecutorDryRunConfig,
    build_remote_executor_dryrun_command,
    build_ssh_executor_dryrun_command,
)


def test_remote_executor_command_uses_dryrun_cli_and_preserves_pythonpath_expansion() -> None:
    config = RemoteExecutorDryRunConfig(
        host="192.0.2.10",
        user="robot",
        remote_project_dir="/home/robot/ai-autonomy-ugv",
    )

    remote = build_remote_executor_dryrun_command(config, executor_armed_preview=True)

    assert remote.startswith("bash -lc '")
    assert "ai_autonomy_runtime.cli.run_verified_executor_dryrun" in remote
    assert "--input-json - --emit-prefixed-receipt --executor-armed-preview" in remote
    assert "export PYTHONPATH=$PWD:${PYTHONPATH:-}" in remote
    assert "run_ugv_teleop" not in remote
    assert "ai_autonomy_runtime.cli.run_verified_executor --" not in remote
    assert "/cmd_vel" not in remote


def test_ssh_executor_command_does_not_request_tty() -> None:
    config = RemoteExecutorDryRunConfig(
        host="192.0.2.10",
        user="robot",
        remote_project_dir="/home/robot/ai-autonomy-ugv",
        identity_file=None,
    )
    remote = build_remote_executor_dryrun_command(config)

    command = build_ssh_executor_dryrun_command(config, remote)

    assert command[0] == "ssh"
    assert "-tt" not in command
    assert command[-1] == remote


def test_remote_executor_command_can_record_preview_state() -> None:
    config = RemoteExecutorDryRunConfig(
        host="192.0.2.10",
        user="robot",
        remote_project_dir="/home/robot/ai-autonomy-ugv",
        state_file="/tmp/replay_state.json",
    )

    remote = build_remote_executor_dryrun_command(
        config,
        executor_armed_preview=True,
        refresh_time_window_preview=True,
        record_dryrun_state_preview=True,
    )

    assert "--state-file /tmp/replay_state.json" in remote
    assert "--record-dryrun-state-preview" in remote
