from __future__ import annotations

from ai_autonomy_runtime.adapters.model_server.vlm_client import StubVLMClient, VLMResponse


class VLMQAAdapter:
    def __init__(self) -> None:
        self.client = StubVLMClient()

    def ask(self, question: str, image_ref: str | None = None) -> VLMResponse:
        return self.client.answer(question=question, image_ref=image_ref)
