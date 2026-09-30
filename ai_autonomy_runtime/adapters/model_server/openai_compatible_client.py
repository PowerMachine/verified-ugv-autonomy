from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from ai_autonomy_runtime.adapters.model_server.llm_client import LLMResponse


@dataclass
class OpenAICompatibleClient:
    backend_name: str
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 30.0

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.0) -> LLMResponse:
        start = time.perf_counter()
        url = self.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        return LLMResponse(
            text=text,
            backend_name=self.backend_name,
            model=self.model,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
