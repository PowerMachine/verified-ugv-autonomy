from __future__ import annotations

import os
import shutil
import subprocess


def detect_ros_version() -> dict[str, object]:
    env_version = os.environ.get("ROS_VERSION")
    ros2_path = shutil.which("ros2")
    rostopic_path = shutil.which("rostopic")
    result = {
        "ros_available": bool(env_version or ros2_path or rostopic_path),
        "ros_version": env_version or None,
        "ros2_cli": ros2_path,
        "ros1_rostopic_cli": rostopic_path,
        "details": "",
    }
    if env_version == "2" or (ros2_path and not env_version):
        result["ros_version"] = "2"
        result["details"] = _run_version_command([ros2_path or "ros2", "--version"])
    elif env_version == "1" or rostopic_path:
        result["ros_version"] = "1"
        result["details"] = _run_version_command(["rosversion", "-d"]) if shutil.which("rosversion") else ""
    return result


def _run_version_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        return (completed.stdout or completed.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
