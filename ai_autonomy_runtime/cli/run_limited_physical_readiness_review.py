from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.adapters.jackal.physical_readiness import (
    PhysicalReadinessConfig,
    evaluate_limited_physical_readiness,
)
from ai_autonomy_runtime.core.audit_logger import _to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(description="Review readiness for a future limited physical Jackal executor.")
    parser.add_argument("--config", default="configs/jackal_limited_physical_readiness.yaml")
    parser.add_argument("--executor-config", default="configs/jackal_executor_safety.yaml")
    parser.add_argument("--remote-suite-summary", required=True)
    parser.add_argument("--live-summary", default=None)
    parser.add_argument("--operator-ack-text", default="")
    parser.add_argument("--estop-available", action="store_true")
    parser.add_argument("--safe-area-confirmed", action="store_true")
    parser.add_argument("--deadman-tested", action="store_true")
    parser.add_argument("--stop-policy-tested", action="store_true")
    parser.add_argument("--inverted-bench-confirmed", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    summary = run_readiness_review(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ready"]:
        raise SystemExit(2)


def run_readiness_review(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output or Path("local_outputs") / "physical_readiness" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)

    config = PhysicalReadinessConfig.from_yaml(args.config)
    executor_config = ExecutorSafetyConfig.from_yaml(args.executor_config)
    remote_suite_summary = _read_json(args.remote_suite_summary)
    live_summary = _read_json(args.live_summary) if args.live_summary else None
    review = evaluate_limited_physical_readiness(
        config=config,
        executor_config=executor_config,
        remote_suite_summary=remote_suite_summary,
        live_summary=live_summary,
        operator_ack_text=args.operator_ack_text,
        estop_available=bool(args.estop_available),
        safe_area_confirmed=bool(args.safe_area_confirmed),
        deadman_tested=bool(args.deadman_tested),
        stop_policy_tested=bool(args.stop_policy_tested),
        inverted_bench_confirmed=bool(args.inverted_bench_confirmed),
    )

    review_payload = review.model_dump(mode="json")
    _write_json(output_dir / "readiness_review.json", review_payload)
    _write_json(
        output_dir / "summary.json",
        {
            "ready": review.ready,
            "reason": review.reason,
            "output_dir": str(output_dir),
            "readiness_review": str(output_dir / "readiness_review.json"),
            "failed_checks": [check.check for check in review.checks if not check.passed],
            "publish_disabled": review.publish_disabled,
            "ros_published": review.ros_published,
            "physical_execution_connected": review.physical_execution_connected,
            "remote_suite_summary": str(args.remote_suite_summary),
            "live_summary": str(args.live_summary) if args.live_summary else None,
            "config": str(args.config),
            "executor_config": str(args.executor_config),
        },
    )
    return json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))


def _read_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()
