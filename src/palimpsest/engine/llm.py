"""LLM completions via Amazon Bedrock (used for consolidation and arbitration).

Two providers behind one interface, selected by model ID:

- ``anthropic.*``  → Claude via the official Anthropic Bedrock (Mantle) client
- anything else    → the Bedrock ``converse`` API via boto3 (e.g. Amazon Nova)

The default model is configurable via ``PALIMPSEST_LLM_MODEL``. Consolidation
and arbitration are short, well-scoped prompts, so any mid-tier model works;
new AWS accounts may not have Anthropic-model entitlement yet, in which case
Amazon Nova is a drop-in default.
"""

from __future__ import annotations

import boto3

from ..config import settings


class BedrockLLM:
    def __init__(self, region: str | None = None, model_id: str | None = None):
        self._region = region or settings.aws_region
        self._model_id = model_id or settings.llm_model_id
        if self._model_id.startswith("anthropic."):
            from anthropic import AnthropicBedrockMantle

            self._anthropic = AnthropicBedrockMantle(aws_region=self._region)
            self._boto = None
        else:
            self._anthropic = None
            self._boto = boto3.client("bedrock-runtime", region_name=self._region)

    def complete(self, prompt: str, max_tokens: int = 512) -> str:
        if self._anthropic is not None:
            response = self._anthropic.messages.create(
                model=self._model_id,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return next((b.text for b in response.content if b.type == "text"), "").strip()

        response = self._boto.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        parts = response["output"]["message"]["content"]
        return next((p["text"] for p in parts if "text" in p), "").strip()


# Backwards-compatible alias (the engine only depends on .complete())
BedrockClaude = BedrockLLM
