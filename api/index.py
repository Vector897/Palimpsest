"""Vercel serverless entry point — wraps the demo panel's FastAPI app.

On Vercel, configuration comes from project environment variables:
PALIMPSEST_DB_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
(and optionally PALIMPSEST_LLM_MODEL).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "demo"))

from web import app  # noqa: E402,F401  (Vercel picks up the ASGI `app`)
