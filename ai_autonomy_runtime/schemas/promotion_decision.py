from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import make_id, utc_now


class PromotionDecisionType(str, Enum):
    REJECT = "reject"
    SUGGEST_ONLY = "suggest_only"
    DRY_RUN = "dry_run"
    HUMAN_APPROVAL = "human_approval"
    LIMITED_PROMOTE = "limited_promote"
    EXECUTE = "execute"
    ROLLBACK = "rollback"


class PromotionDecision(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    decision_id: str = Field(default_factory=lambda: make_id("decision"))
    artifact_id: str
    decision: PromotionDecisionType
    reason: str
    passed_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    rollback_available: bool = False
    timestamp: datetime = Field(default_factory=utc_now)
