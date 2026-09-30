from __future__ import annotations

import argparse

from ai_autonomy_runtime.cli.run_remote_ugv_live_local import build_ssh_stream_command


def test_ssh_stream_command_preserves_remote_pythonpath_expansion() -> None:
    args = argparse.Namespace(
        user="robot",
        host="192.0.2.10",
        identity_file=None,
        remote_project_dir="/home/robot/ai-autonomy-ugv",
        run_id="test_run",
        sample_hz=5,
        duration=10,
    )

    command = build_ssh_stream_command(args)
    remote = command[-1]

    assert remote.startswith("bash -lc '")
    assert 'export PYTHONPATH="$PWD:${PYTHONPATH:-}"' in remote
