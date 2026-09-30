from __future__ import annotations

import json
import time
from typing import Any

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact
from ai_autonomy_runtime.schemas.skill_graph import SkillGraph


def run_json_size_latency_benchmark(schemas: list[str], iterations: int = 5) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for schema_name in schemas:
        payload, model = _payload_for_schema(schema_name)
        text = json.dumps(payload, ensure_ascii=False)
        parse_times: list[float] = []
        validation_times: list[float] = []
        malformed = 0
        violations = 0
        for _ in range(iterations):
            start = time.perf_counter()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                malformed += 1
                continue
            parse_times.append((time.perf_counter() - start) * 1000.0)

            start = time.perf_counter()
            try:
                model.model_validate(parsed)
            except Exception:
                violations += 1
            validation_times.append((time.perf_counter() - start) * 1000.0)
        rows.append(
            {
                "schema": schema_name,
                "json_length_bytes": len(text.encode("utf-8")),
                "parse_latency_ms": _mean(parse_times),
                "validation_latency_ms": _mean(validation_times),
                "malformed_json_rate": malformed / max(iterations, 1),
                "schema_violation_rate": violations / max(iterations, 1),
                "total_candidate_latency_ms": _mean(parse_times) + _mean(validation_times),
                "deadline_miss_rate": 0.0,
            }
        )
    return rows


def _payload_for_schema(schema_name: str) -> tuple[dict[str, Any], type]:
    if schema_name == "compact_velocity":
        return (
            {
                "action_type": "velocity_candidate",
                "parameters": {"linear_x": 0.05, "angular_z": 0.0, "sequence_id": 1},
                "ttl_ms": 500,
                "expected_duration_ms": 100,
                "risk_level": "medium",
                "requires_physical_execution": True,
                "source_model": "mock_model",
            },
            ActionCandidate,
        )
    if schema_name == "primitive_sequence":
        return (
            {
                "action_type": "primitive_sequence",
                "parameters": {"steps": [{"action": "wait", "duration_ms": 100}], "sequence_id": 1},
                "ttl_ms": 1000,
                "expected_duration_ms": 100,
                "risk_level": "low",
                "requires_physical_execution": False,
                "source_model": "mock_model",
            },
            ActionCandidate,
        )
    if schema_name == "skill_graph":
        return (
            {
                "nodes": [
                    {"skill_type": "observe", "parameters": {"source": "camera"}, "risk_level": "low"},
                    {"skill_type": "report", "parameters": {"format": "json"}, "risk_level": "low"},
                ],
                "edges": [{"source_node_id": "node_a", "target_node_id": "node_b", "condition": "success"}],
                "metadata": {"source": "benchmark"},
            },
            SkillGraph,
        )
    return (
        {
            "artifact_type": "report",
            "source_agent": "mock_model",
            "payload": {"summary": "Read-only inspection report.", "recommendations": ["continue observing"]},
            "target_system": "jackal",
            "risk_level": "low",
            "requires_physical_execution": False,
            "requires_human_approval": False,
            "metadata": {"evidence_score": 1.0},
        },
        AgenticArtifact,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
