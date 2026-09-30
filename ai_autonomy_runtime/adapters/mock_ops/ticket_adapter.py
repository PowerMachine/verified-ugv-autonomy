from __future__ import annotations

from ai_autonomy_runtime.schemas.common import make_id


class TicketAdapter:
    def create_ticket(self, title: str, body: str, severity: str = "info") -> dict[str, str]:
        return {"ticket_id": make_id("ticket"), "title": title, "body": body, "severity": severity, "status": "mock_created"}
