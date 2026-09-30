from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import make_id, utc_now


class Observation(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    observation_id: str = Field(default_factory=lambda: make_id("obs"))
    source: str
    observed_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
