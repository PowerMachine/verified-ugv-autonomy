from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    accepted: bool
    executed: bool
    publish_disabled: bool = False
    ros_published: bool = False
    rejected_reason: Optional[str] = None
    publish_topic: Optional[str] = None
    publish_count: int = Field(ge=0)
    stop_published: bool
    executor_latency_ms: float = Field(ge=0)
    cmd_vel_out_observed: Optional[bool] = None
    odom_observed: Optional[bool] = None
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)
