from __future__ import annotations

import time

from ai_autonomy_runtime.adapters.jackal.safe_command_wrapper import SafeCommandWrapper
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope


def run_control_deadline_benchmark(ttl_ms: int = 500) -> dict[str, object]:
    start = time.perf_counter()
    candidate = ActionCandidate(
        action_type=ActionType.VELOCITY_CANDIDATE,
        parameters={"linear_x": 0.05, "angular_z": 0.0, "sequence_id": 1},
        ttl_ms=ttl_ms,
        expected_duration_ms=100,
        risk_level=RiskLevel.MEDIUM,
        requires_physical_execution=True,
        source_model="mock_model",
    )
    wrapper = SafeCommandWrapper()
    safety_start = time.perf_counter()
    safety = wrapper.evaluate(candidate, SafetyEnvelope(), require_physical_gate=True)
    safety_latency_ms = (time.perf_counter() - safety_start) * 1000.0
    total_latency_ms = (time.perf_counter() - start) * 1000.0
    return {
        "candidate_ttl_ms": ttl_ms,
        "total_latency_ms": total_latency_ms,
        "deadline_miss": total_latency_ms > ttl_ms,
        "stale_command_rejected": candidate.is_expired(),
        "safety_wrapper_latency_ms": safety_latency_ms,
        "safety_accepted": safety.accepted,
        "safety_reason": safety.reason,
    }
