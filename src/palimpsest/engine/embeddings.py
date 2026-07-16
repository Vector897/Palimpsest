"""Text embeddings via Amazon Bedrock (Titan Text Embeddings V2)."""

from __future__ import annotations

import json

import boto3

from ..config import settings


class TitanEmbedder:
    """Embeds text into vectors suitable for CockroachDB's cosine vector index."""

    def __init__(self, region: str | None = None, model_id: str | None = None):
        self._client = boto3.client("bedrock-runtime", region_name=region or settings.aws_region)
        self._model_id = model_id or settings.embed_model_id
        self.dimensions = settings.embed_dimensions

    def embed(self, text: str) -> list[float]:
        body = json.dumps(
            {"inputText": text[:8000], "dimensions": self.dimensions, "normalize": True}
        )
        response = self._client.invoke_model(modelId=self._model_id, body=body)
        return json.loads(response["body"].read())["embedding"]


def to_vector_literal(embedding: list[float]) -> str:
    """Render an embedding as a CockroachDB VECTOR literal string."""
    return "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
