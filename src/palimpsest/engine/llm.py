"""LLM calls via Claude on Amazon Bedrock (used for consolidation and arbitration)."""

from __future__ import annotations

from anthropic import AnthropicBedrockMantle

from ..config import settings


class BedrockClaude:
    def __init__(self, region: str | None = None, model_id: str | None = None):
        self._client = AnthropicBedrockMantle(aws_region=region or settings.aws_region)
        self._model_id = model_id or settings.llm_model_id

    def complete(self, prompt: str, max_tokens: int = 512) -> str:
        response = self._client.messages.create(
            model=self._model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return next((b.text for b in response.content if b.type == "text"), "").strip()
