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
5. Enable live read-only X calls only after scopes, rate limits, local cost ledger, Usage API reconciliation, and Developer Console reconciliation are verified.
6. Keep `ALLOW_NON_TEST_MODE_WRITE=false` through staging.
7. Enable non-test writes only after admission readiness, operator workflow, audit logging, Track A consent handling, and rollback are validated.

## Rollback

Disable live calls by setting:

```bash
ALLOW_LIVE_X_API=false
ALLOW_NON_TEST_MODE_WRITE=false
SEARCH_PROVIDER=fixture
LLM_PROVIDER=fixture
COMMUNITY_NOTES_DATA_USE_PURPOSE=community_notes_ai_note_writing
OPERATIONAL_EVALS_DIRECTLY_NECESSARY=true
TRACK_A_REQUIRES_EXPRESS_CONSENT=true
REQUIRE_BOT_IDENTITY_DISCLOSURE=true
USAGE_API_RECONCILIATION_REQUIRED=true
DEVELOPER_CONSOLE_RECONCILIATION_REQUIRED=true
```

Then redeploy the API.
