from __future__ import annotations

import argparse

from ai_autonomy_runtime.adapters.jackal.observer import JackalObserver
from ai_autonomy_runtime.cli.common import print_json
from ai_autonomy_runtime.core.audit_logger import AuditLogger, create_run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jackal observer in read-only mode.")
    parser.add_argument("--mode", default="read_only", choices=["read_only"])
    parser.add_argument("--output", default="runs/jackal_observer")
    args = parser.parse_args()
    run_dir = create_run_dir(args.output)
    logger = AuditLogger(run_dir)
    event = JackalObserver().observe_once()
    logger.log_event(event)
    summary = {"run_dir": str(run_dir), "mode": args.mode, "event": event, "physical_execution": False}
    logger.write_summary(summary)
    print_json(summary)


if __name__ == "__main__":
    main()
