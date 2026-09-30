from __future__ import annotations

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate


class CriticAgent:
    def critique(self, candidate: ActionCandidate) -> dict[str, object]:
        concerns: list[str] = []
        if candidate.requires_physical_execution:
            concerns.append("physical execution requires deterministic safety wrapper and operator approval")
        if candidate.ttl_ms <= 0:
            concerns.append("ttl missing")
        return {"candidate_id": candidate.candidate_id, "concerns": concerns, "passed": not concerns}
