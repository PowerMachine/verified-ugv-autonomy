from __future__ import annotations

import argparse

from ai_autonomy_runtime.adapters.ros_common.topic_discovery import discover_ros_environment
from ai_autonomy_runtime.core.audit_logger import AuditLogger, create_run_dir
from ai_autonomy_runtime.cli.common import print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only ROS discovery.")
    parser.add_argument("--output", default="runs/ros_discovery")
    args = parser.parse_args()

    run_dir = create_run_dir(args.output)
    logger = AuditLogger(run_dir)
    discovery = discover_ros_environment()
    logger.write_summary({"ros_discovery": discovery})
    (run_dir / "ros_discovery.json").write_text(printable_json(discovery), encoding="utf-8")
    print_json({"run_dir": str(run_dir), "ros_available": discovery["detection"]["ros_available"], "discovery": discovery})


def printable_json(payload: object) -> str:
    import json

    from ai_autonomy_runtime.core.audit_logger import _to_jsonable

    return json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
