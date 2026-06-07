# Deployment

## Local

```bash
cp infra/.env.example .env
make setup
make db-up
make migrate
make seed-fixtures
make dev
```

The local server runs at `http://localhost:8000` and serves both API and UI.

## Render Web Service

The repo now includes a root-level `render.yaml` Blueprint. For a new Render setup, use **New -> Blueprint**, select this GitHub repo, and Render will create/update the Python web service and Postgres settings from the checked-in config.

For an existing manually created Web Service, either sync the Blueprint or use these settings:

Use the Python 3 runtime, leave the root directory blank, and deploy from `main`.

Build command:

```bash
pip install -r requirements.txt && python3 -m compileall apps/api/app
```

Start command:

```bash
PYTHONPATH=apps/api python3 apps/api/app/main.py --host 0.0.0.0 --port $PORT
```

If Render is still configured with the older command below, it will now also work because the app defaults to `0.0.0.0` whenever Render provides `PORT`:

```bash
PYTHONPATH=apps/api python3 apps/api/app/main.py --port $PORT
```

The app is a dependency-light Python HTTP server for the fixture build. Do not use `uvicorn app.main:app` unless the backend is later upgraded to an ASGI/FastAPI application.

Set `PERSISTENCE_PROVIDER=postgres` and `DATABASE_URL` to the Render Postgres internal database URL to persist app records. The app creates the required JSONB record-store table at startup.

If the deploy log shows `ModuleNotFoundError: No module named 'psycopg'`, the service is still using an old build command. Update the build command to install `requirements.txt` or sync the root `render.yaml` Blueprint.

The deployment exposes `/api/health` for Render health checks and `/api/governance` for the public-safe CommunityNotes14 governance summary.

Keep these governance defaults in Render unless deliberately changing phase:

```bash
EMERGENCY_STOP_EXTERNAL_WRITES=false
APPROVED_MULTIMODAL_WORKFLOW_ENABLED=false
GOVERNANCE_POLICY_VERSION=community-notes14-governance-v1
```

## Staging Production Stack

Recommended production upgrade:

- API: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx, uvicorn.
- DB: managed Postgres with pgvector.
- Web: Next.js with TypeScript and TanStack Query.
- Search: fixture provider in staging, Brave/Search provider behind env flags.
- LLM: fixture provider in staging, runtime provider with strict JSON schema calls.
- Hosting: Vercel or Cloudflare for frontend, containerized API on Render/Fly/Cloud Run, managed Postgres, object storage for retrieved artifacts.

## Rollout

1. Deploy with `ALLOW_LIVE_X_API=false`, `ALLOW_NON_TEST_MODE_WRITE=false`, and fixture providers.
2. Run offline evals and fixture E2E.
3. Verify `COMMUNITY_NOTES_DATA_USE_PURPOSE=community_notes_ai_note_writing` and `OPERATIONAL_EVALS_DIRECTLY_NECESSARY=true`.
4. Configure Track B bot-profile disclosure and responsible-party identity before any write path is considered.
5. Enable Postgres persistence first and confirm `/api/health` reports `persistence_provider=postgres`.
6. Enable live read-only X calls with `ALLOW_LIVE_X_API=true` only after scopes, rate limits, local cost ledger, Usage API reconciliation, and Developer Console reconciliation are verified.
7. Keep `ALLOW_LIVE_X_WRITE=false` and `ALLOW_NON_TEST_MODE_WRITE=false` through read-only staging.
8. Confirm `/api/governance` shows emergency stop clear, methodology card present, policy drift requiring operator review before non-test writes, and official scoring replay available.
9. Enable live test-mode writes only after deliberately setting `ALLOW_LIVE_X_WRITE=true`.
10. Enable non-test writes only after admission readiness, operator workflow, audit logging, Track A consent handling, governance gates, policy drift review, and rollback are validated.

## Rollback

Disable live calls by setting:

```bash
ALLOW_LIVE_X_API=false
ALLOW_LIVE_X_WRITE=false
ALLOW_NON_TEST_MODE_WRITE=false
SEARCH_PROVIDER=fixture
LLM_PROVIDER=fixture
COMMUNITY_NOTES_DATA_USE_PURPOSE=community_notes_ai_note_writing
OPERATIONAL_EVALS_DIRECTLY_NECESSARY=true
TRACK_A_REQUIRES_EXPRESS_CONSENT=true
REQUIRE_BOT_IDENTITY_DISCLOSURE=true
USAGE_API_RECONCILIATION_REQUIRED=true
DEVELOPER_CONSOLE_RECONCILIATION_REQUIRED=true
EMERGENCY_STOP_EXTERNAL_WRITES=true
APPROVED_MULTIMODAL_WORKFLOW_ENABLED=false
```

Then redeploy the API.
