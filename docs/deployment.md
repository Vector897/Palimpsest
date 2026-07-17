# Deployment

Palimpsest has three deployable pieces. The core library and MCP server run
anywhere Python 3.11+ does; the two below are the hosted demo and the nightly
job.

## Configuration

All configuration is environment-based — no secrets in the repo.

| Variable | Purpose |
|---|---|
| `PALIMPSEST_DB_URL` | CockroachDB connection URI (`postgresql://…?sslmode=verify-full`) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Bedrock credentials |
| `AWS_REGION` | Bedrock region (default `us-east-1`) |
| `PALIMPSEST_LLM_MODEL` | Consolidation/arbitration model (default `us.amazon.nova-pro-v1:0`; set `anthropic.claude-opus-4-8` where the account has Anthropic-model access) |
| `PALIMPSEST_OWNER` | Agent identity for the MCP server (one memory space per value) |

Locally, `PALIMPSEST_DB_URL` can be replaced by a `.crdb-connection` file in the
project root (git-ignored). `verify-full` TLS uses the bundled certifi CA store.

## Demo web panel — Vercel

The panel is a FastAPI app exposed as a single serverless function.

- `api/index.py` — the ASGI entry point Vercel invokes
- `vercel.json` — routes all paths to the function; `maxDuration` is raised to
  60s because a morning triage makes several sequential Bedrock calls
- `requirements.txt` — the serverless build's dependencies

Deploy:

1. Import the repo in the Vercel dashboard (root directory: `CODE`).
2. Add the environment variables above (`PALIMPSEST_DB_URL`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`).
3. Deploy. The panel is served from the project's Vercel URL.

## Nightly consolidation — AWS Lambda

`src/palimpsest/adapters/lambda_consolidate.py` exposes `handler(event,
context)`: for every agent with fresh episodic memory it consolidates and then
applies the forgetting curve — the same code the demo's `night` command runs.

Recommended shape:

- **Packaging**: container image (psycopg needs a Linux wheel), arm64, 512 MB.
- **Env**: `PALIMPSEST_DB_URL`, `PALIMPSEST_LLM_MODEL`, `AWS_REGION`.
- **IAM**: the execution role needs `bedrock:InvokeModel` plus the basic Lambda
  logging permissions — nothing else (least privilege).
- **Schedule**: an EventBridge Scheduler rule, e.g. `cron(0 3 * * ? *)` for a
  nightly 03:00 UTC run.

The handler is idempotent: re-running only consolidates memory that is still
within the 24-hour window, and duplicate facts reinforce rather than duplicate.
