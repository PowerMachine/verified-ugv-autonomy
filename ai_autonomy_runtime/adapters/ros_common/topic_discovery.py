from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.ros_common.message_utils import identify_likely_topics
from ai_autonomy_runtime.adapters.ros_common.ros_version_detector import detect_ros_version
from ai_autonomy_runtime.core.audit_logger import _to_jsonable

import json


def discover_ros_environment() -> dict[str, Any]:
    detection = detect_ros_version()
    ros_version = str(detection.get("ros_version") or "")
    topics: list[dict[str, str]] = []
    errors: list[str] = []
    if ros_version == "2":
        topics, errors = _discover_ros2_topics()
    elif ros_version == "1":
        topics, errors = _discover_ros1_topics()
    else:
        errors.append("ROS CLI unavailable; discovery returned stub result.")
    return {
        "detection": detection,
        "topics": topics,
        "likely_topics": identify_likely_topics(topics),
        "errors": errors,
        "read_only": True,
    }


def write_discovery(output_dir: str | Path) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "ros_discovery.json"
    path.write_text(json.dumps(_to_jsonable(discover_ros_environment()), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _discover_ros2_topics() -> tuple[list[dict[str, str]], list[str]]:
    completed, error = _run(["ros2", "topic", "list", "-t"])
    if error:
        return [], [error]
    topics: list[dict[str, str]] = []
    for line in completed.splitlines():
        line = line.strip()
        if not line:
            continue
        if " [" in line and line.endswith("]"):
            name, msg_type = line.rsplit(" [", 1)
            topics.append({"name": name.strip(), "type": msg_type[:-1].strip()})
        else:
            topics.append({"name": line, "type": ""})
    return topics, []


def _discover_ros1_topics() -> tuple[list[dict[str, str]], list[str]]:
    verbose, verbose_error = _run(["rostopic", "list", "-v"], timeout_s=10)
    if not verbose_error:
        topics = _parse_ros1_verbose_topics(verbose)
        if topics:
            return topics, []

    completed, error = _run(["rostopic", "list"])
    if error:
        return [], [error]
    topics: list[dict[str, str]] = []
    errors: list[str] = []
    for line in completed.splitlines():
        name = line.strip()
        if not name:
            continue
        msg_type, type_error = _run(["rostopic", "type", name], timeout_s=2)
        if type_error:
            errors.append(type_error)
        topics.append({"name": name, "type": msg_type.strip() if msg_type else ""})
    if verbose_error:
        errors.append(verbose_error)
    return topics, errors


def _parse_ros1_verbose_topics(output: str) -> list[dict[str, str]]:
    topics: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("* "):
            continue
        topic = line[2:].strip()
        if " [" in topic and "]" in topic:
            name, rest = topic.split(" [", 1)
            msg_type = rest.split("]", 1)[0].strip()
        else:
            parts = topic.split()
            name = parts[0] if parts else ""
            msg_type = ""
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        topics.append({"name": name, "type": msg_type})
    return topics


def _run(command: list[str], timeout_s: float = 5) -> tuple[str, str | None]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", str(exc)
    if completed.returncode != 0:
        return "", (completed.stderr or completed.stdout).strip()
    return completed.stdout, None
