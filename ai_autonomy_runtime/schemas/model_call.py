from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import make_id, utc_now


class ModelCall(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    call_id: str = Field(default_factory=lambda: make_id("model_call"))
    backend_name: str
    model: str
    started_at: datetime = Field(default_factory=utc_now)
    latency_ms: float = 0.0
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
