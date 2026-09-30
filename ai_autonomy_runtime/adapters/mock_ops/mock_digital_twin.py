from __future__ import annotations


class MockDigitalTwin:
    def update(self, patch: dict[str, object]) -> dict[str, object]:
        return {"status": "mock_updated", "patch": patch}
