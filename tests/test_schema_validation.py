from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.agentic_artifact import AgenticArtifact, ArtifactType


def test_action_candidate_schema_accepts_safe_report() -> None:
    candidate = ActionCandidate(action_type=ActionType.REPORT_ONLY, parameters={"report": "ok"})
    assert candidate.action_type == "report_only"
    assert not candidate.requires_physical_execution
    assert not candidate.is_expired()


def test_action_candidate_schema_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        ActionCandidate(action_type="fly", parameters={})


def test_agentic_artifact_schema() -> None:
    artifact = AgenticArtifact(
        artifact_type=ArtifactType.REPORT,
        source_agent="test",
        payload={"summary": "read-only"},
        target_system="jackal",
    )
    assert artifact.artifact_type == "report"
    assert artifact.metadata == {}
