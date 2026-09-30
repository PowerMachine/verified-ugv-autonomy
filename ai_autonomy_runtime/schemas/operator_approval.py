from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_autonomy_runtime.schemas.common import make_id
from ai_autonomy_runtime.schemas.verified_command import current_time_ms


class OperatorApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(default_factory=lambda: make_id("approval"), min_length=1)
    operator_id: str = Field(default="manual_operator", min_length=1)
    approved: bool = False
    approved_at_ms: int = Field(default_factory=current_time_ms, ge=0)
    expires_at_ms: int | None = Field(default=None, ge=0)
    command_id: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "OperatorApproval":
        if self.expires_at_ms is not None and self.expires_at_ms <= self.approved_at_ms:
            raise ValueError("expires_at_ms must be greater than approved_at_ms")
        return self
