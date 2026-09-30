from __future__ import annotations


def identify_likely_topics(topics: list[dict[str, str]]) -> dict[str, str | None]:
    names = [topic.get("name", "") for topic in topics]
    return {
        "velocity_command": _first_match(names, ["cmd_vel", "velocity_command"]),
        "odometry": _first_match(names, ["odom", "odometry"]),
        "scan": _first_match(names, ["scan", "lidar", "laser"]),
        "camera": _first_match(names, ["camera", "image_raw", "rgb"]),
        "tf": _first_match(names, ["/tf", "tf_static"]),
        "diagnostics": _first_match(names, ["diagnostics", "diagnostic"]),
    }


def _first_match(names: list[str], needles: list[str]) -> str | None:
    for needle in needles:
        for name in names:
            if needle.lower() in name.lower():
                return name
    return None
