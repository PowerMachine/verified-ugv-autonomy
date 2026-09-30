from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel


AUDIT_JSONL_FILES = {
    "events": "events.jsonl",
    "model_calls": "model_calls.jsonl",
    "agentic_artifacts": "agentic_artifacts.jsonl",
    "verification_results": "verification_results.jsonl",
    "promotion_decisions": "promotion_decisions.jsonl",
    "safety_checks": "safety_checks.jsonl",
}


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_run_dir(base_dir: str | Path) -> Path:
    base = Path(base_dir)
    run_dir = base / timestamp_slug() if base.name != timestamp_slug() else base
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


class AuditLogger:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for filename in AUDIT_JSONL_FILES.values():
            (self.run_dir / filename).touch(exist_ok=True)
        self.latency_csv = self.run_dir / "latency_metrics.csv"
        if not self.latency_csv.exists():
            with self.latency_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["name", "latency_ms", "metadata_json"])
                writer.writeheader()

    def log_event(self, payload: Any) -> None:
        self._append_jsonl("events", payload)

    def log_model_call(self, payload: Any) -> None:
        self._append_jsonl("model_calls", payload)

    def log_agentic_artifact(self, payload: Any) -> None:
        self._append_jsonl("agentic_artifacts", payload)

    def log_verification_result(self, payload: Any) -> None:
        self._append_jsonl("verification_results", payload)

    def log_promotion_decision(self, payload: Any) -> None:
        self._append_jsonl("promotion_decisions", payload)

    def log_safety_check(self, payload: Any) -> None:
        self._append_jsonl("safety_checks", payload)

    def log_latency_metric(self, name: str, latency_ms: float, metadata: dict[str, Any] | None = None) -> None:
        with self.latency_csv.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["name", "latency_ms", "metadata_json"])
            writer.writerow(
                {
                    "name": name,
                    "latency_ms": f"{latency_ms:.6f}",
                    "metadata_json": json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                }
            )

    def write_summary(self, summary: dict[str, Any]) -> Path:
        path = self.run_dir / "summary.json"
        path.write_text(json.dumps(_to_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _append_jsonl(self, channel: str, payload: Any) -> None:
        path = self.run_dir / AUDIT_JSONL_FILES[channel]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_to_jsonable(payload), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value
