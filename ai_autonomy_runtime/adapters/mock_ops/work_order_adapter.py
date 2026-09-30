from __future__ import annotations

from ai_autonomy_runtime.schemas.common import make_id


class WorkOrderAdapter:
    def create_work_order(self, action: str, evidence: list[str] | None = None) -> dict[str, object]:
        return {"work_order_id": make_id("wo"), "action": action, "evidence": evidence or [], "status": "mock_created"}
