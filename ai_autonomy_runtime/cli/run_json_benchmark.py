from __future__ import annotations

import argparse

from ai_autonomy_runtime.benchmarks.json_size_latency_benchmark import run_json_size_latency_benchmark
from ai_autonomy_runtime.cli.common import print_json, write_csv
from ai_autonomy_runtime.core.audit_logger import AuditLogger, create_run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark JSON parse and validation latency.")
    parser.add_argument("--schemas", default="compact_velocity,primitive_sequence,skill_graph,report_only")
    parser.add_argument("--output", default="runs/json_latency")
    args = parser.parse_args()
    run_dir = create_run_dir(args.output)
    rows = run_json_size_latency_benchmark([item.strip() for item in args.schemas.split(",") if item.strip()])
    write_csv(run_dir / "json_latency.csv", rows)
    logger = AuditLogger(run_dir)
    logger.write_summary({"rows": rows})
    print_json({"run_dir": str(run_dir), "rows": rows})


if __name__ == "__main__":
    main()
