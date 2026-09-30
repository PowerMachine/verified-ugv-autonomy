from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import RiskLevel, make_id


class SkillNode(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    node_id: str = Field(default_factory=lambda: make_id("node"))
    skill_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW


class SkillEdge(BaseModel):
    source_node_id: str
    target_node_id: str
    condition: str = "success"


class SkillGraph(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    graph_id: str = Field(default_factory=lambda: make_id("skill_graph"))
    nodes: list[SkillNode] = Field(default_factory=list)
    edges: list[SkillEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
