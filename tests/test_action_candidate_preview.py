from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.verifier.ugv_safety_validator import UGVSafetyValidator


def test_preview_accepts_safe_forward_candidate() -> None:
    candidate = ActionCandidate(
        action_type="forward",
        parameters={"linear": 0.05, "duration_ms": 700},
        expected_duration_ms=700,
    )

    result = UGVSafetyValidator().validate(candidate)

    assert result.passed
    assert result.metadata["executable"] is True


def test_preview_rejects_excessive_linear_speed() -> None:
    candidate = ActionCandidate(
        action_type="forward",
        parameters={"linear": 0.5, "duration_ms": 700},
        expected_duration_ms=700,
    )

    result = UGVSafetyValidator().validate(candidate)

    assert not result.passed
    assert not result.metadata["checks"]["linear_limit"]


def test_preview_rejects_excessive_duration() -> None:
    candidate = ActionCandidate(
        action_type="forward",
        parameters={"linear": 0.05, "duration_ms": 10000},
        expected_duration_ms=10000,
    )

    result = UGVSafetyValidator().validate(candidate)

    assert not result.passed
    assert not result.metadata["checks"]["duration_limit"]


def test_preview_rejects_unknown_action_type() -> None:
    with pytest.raises(ValidationError):
        ActionCandidate(action_type="fly", parameters={})


def test_physical_request_without_approval_is_not_executable() -> None:
    candidate = ActionCandidate(
        action_type="forward",
        parameters={"linear": 0.05, "duration_ms": 700},
        expected_duration_ms=700,
        requires_physical_execution=True,
    )

    result = UGVSafetyValidator().validate(candidate, human_approved=False)

    assert not result.passed
    assert result.metadata["executable"] is False
    assert not result.metadata["checks"]["physical_approval"]
