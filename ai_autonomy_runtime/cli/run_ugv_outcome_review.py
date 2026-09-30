from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.jackal.outcome_monitor import (
    load_receipt,
    parse_telemetry_log,
    review_bounded_command_outcome,
)
from ai_autonomy_runtime.core.audit_logger import _to_jsonable
from ai_autonomy_runtime.live.outcome_visualization import build_outcome_timeline, write_outcome_html


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a bounded UGV command outcome from telemetry and receipt logs.")
    parser.add_argument("--telemetry-log", required=True)
    parser.add_argument("--receipt-file", required=True)
    parser.add_argument("--expected-linear", type=float, required=True)
    parser.add_argument("--expected-angular", type=float, required=True)
    parser.add_argument("--expected-duration-ms", type=int, required=True)
    parser.add_argument("--linear-tolerance", type=float, default=0.01)
    parser.add_argument("--angular-tolerance", type=float, default=0.02)
    parser.add_argument("--zero-epsilon", type=float, default=1e-6)
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-require-cmd-out", action="store_true")
    parser.add_argument("--no-require-odom", action="store_true")
    parser.add_argument("--no-require-feedback", action="store_true")
    parser.add_argument("--no-require-stop", action="store_true")
    args = parser.parse_args()

    summary = run_outcome_review(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "exception_required":
        raise SystemExit(2)


def run_outcome_review(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output or Path("local_outputs") / "outcome_review" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)

    receipt = load_receipt(args.receipt_file)
    review = review_bounded_command_outcome(
        telemetry_log=args.telemetry_log,
        receipt=receipt,
        expected_linear_x=args.expected_linear,
        expected_angular_z=args.expected_angular,
        expected_duration_ms=args.expected_duration_ms,
        linear_tolerance=args.linear_tolerance,
        angular_tolerance=args.angular_tolerance,
        zero_epsilon=args.zero_epsilon,
        require_cmd_out=not bool(args.no_require_cmd_out),
        require_odom=not bool(args.no_require_odom),
        require_feedback=not bool(args.no_require_feedback),
        require_stop=not bool(args.no_require_stop),
    )
    review_payload = _to_jsonable(review)
    parsed_telemetry = parse_telemetry_log(args.telemetry_log)
    timeline = build_outcome_timeline(parsed_telemetry["states"])
    _write_json(output_dir / "outcome_review.json", review_payload)
    _write_json(output_dir / "outcome_timeline.json", {"timeline": timeline})
    outcome_html = write_outcome_html(
        output_dir / "outcome_review.html",
        review_payload=review_payload,
        timeline=timeline,
    )
    summary = {
        "status": review.status,
        "exception_required": review.exception_required,
        "reason": review.reason,
        "command_id": review.command_id,
        "output_dir": str(output_dir),
        "outcome_review": str(output_dir / "outcome_review.json"),
        "outcome_timeline": str(output_dir / "outcome_timeline.json"),
        "outcome_html": str(outcome_html),
        "telemetry_log": args.telemetry_log,
        "receipt_file": args.receipt_file,
        "sample_count": review.observed.get("sample_count"),
        "cmd_in_nonzero_samples": review.observed.get("cmd_in", {}).get("nonzero_samples"),
        "cmd_out_nonzero_samples": review.observed.get("cmd_out", {}).get("nonzero_samples"),
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()
