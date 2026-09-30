from __future__ import annotations

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate


class MockSimulator:
    def simulate(self, candidate: ActionCandidate) -> dict[str, object]:
        return {
            "candidate_id": candidate.candidate_id,
            "action_type": str(candidate.action_type),
            "collision_predicted": bool(candidate.parameters.get("obstacle_detected", False)),
            "estimated_duration_ms": candidate.expected_duration_ms,
            "status": "ok",
        }
