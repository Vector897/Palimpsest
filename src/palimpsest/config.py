"""Configuration.

The database URL is resolved in order:
1. ``PALIMPSEST_DB_URL`` environment variable
2. a ``.crdb-connection`` file (single-line postgresql:// URI) in the current
   working directory or any parent directory

Secrets never live in code or in the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _find_connection_file(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        f = candidate / ".crdb-connection"
        if f.is_file():
            return f
    return None


def _resolve_db_url() -> str:
    if url := os.environ.get("PALIMPSEST_DB_URL"):
        return url
    if f := _find_connection_file():
        url = f.read_text(encoding="utf-8").strip()
        if sslmode := os.environ.get("PALIMPSEST_DB_SSLMODE"):
            url = url.replace("sslmode=verify-full", f"sslmode={sslmode}")
        url += ("&" if "?" in url else "?") + "connect_timeout=10"
        # CockroachDB Cloud serves Let's Encrypt certs; full verification works
        # against the certifi bundle (OpenSSL's default store is empty on Windows)
        if "sslmode=verify-full" in url and "sslrootcert" not in url:
            import certifi

            url += "&sslrootcert=" + certifi.where()
        return url
    raise RuntimeError(
        "No database URL: set PALIMPSEST_DB_URL or place a .crdb-connection file "
        "in the project directory."
    )


@dataclass(frozen=True)
class Settings:
    db_url: str = field(default_factory=_resolve_db_url)
    aws_region: str = os.environ.get("PALIMPSEST_AWS_REGION", "us-east-1")
    embed_model_id: str = os.environ.get(
        "PALIMPSEST_EMBED_MODEL", "amazon.titan-embed-text-v2:0"
    )
    embed_dimensions: int = int(os.environ.get("PALIMPSEST_EMBED_DIM", "1024"))
    # "anthropic.claude-opus-4-8" once the account has Anthropic-model entitlement;
    # Amazon Nova is auto-enabled on new accounts and handles these short prompts well
    llm_model_id: str = os.environ.get(
        "PALIMPSEST_LLM_MODEL", "us.amazon.nova-pro-v1:0"
    )
    # cosine-distance bands for conflict detection during consolidation
    duplicate_below: float = 0.10   # closer than this → same fact, just reinforce
    conflict_below: float = 0.45    # between bands → same topic, arbitrate
    # forgetting curve
    decay_factor: float = 0.95
    archive_below: float = 0.05


settings = Settings()
