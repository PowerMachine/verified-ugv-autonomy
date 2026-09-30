from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import RiskLevel, make_id, utc_now


class ArtifactType(str, Enum):
    CODE_PATCH = "code_patch"
    CONFIG_PATCH = "config_patch"
    PROMPT_PATCH = "prompt_patch"
    WORKFLOW_CANDIDATE = "workflow_candidate"
    REPORT = "report"
    ACTION_CANDIDATE = "action_candidate"
    SKILL_GRAPH = "skill_graph"
    ROBOT_PRIMITIVE_SEQUENCE = "robot_primitive_sequence"
    DIGITAL_TWIN_UPDATE = "digital_twin_update"


class AgenticArtifact(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    artifact_id: str = Field(default_factory=lambda: make_id("artifact"))
    artifact_type: ArtifactType
    source_agent: str = "unknown"
    created_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    target_system: str = "unknown"
    risk_level: RiskLevel = RiskLevel.LOW
    requires_physical_execution: bool = False
    requires_human_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
