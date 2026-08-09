"""Vercel serverless entry point — wraps the demo panel's FastAPI app.

On Vercel, configuration comes from project environment variables:
PALIMPSEST_DB_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
(and optionally PALIMPSEST_LLM_MODEL).

Routing note: the vercel.json rewrite maps every request to
``/api/index/<original path>``. Vercel's Python runtime hands the ASGI app the
*destination* path, so this shim strips the ``/api/index`` prefix before the
FastAPI app routes. It is also a no-op when the runtime passes the original path
directly (no route begins with ``/api/index``), so it is correct under both
behaviours.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "demo"))

from web import app as _fastapi_app  # noqa: E402

_PREFIX = "/api/index"


async def app(scope, receive, send):
    if scope["type"] in ("http", "websocket"):
        path = scope.get("path", "") or ""
        if path == _PREFIX:
            path = "/"
        elif path.startswith(_PREFIX + "/"):
            path = path[len(_PREFIX):] or "/"
        scope = dict(scope, path=path, raw_path=path.encode("utf-8"))
    await _fastapi_app(scope, receive, send)
