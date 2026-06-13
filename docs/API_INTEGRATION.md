# API Integration

## X Client Methods

`XCommunityNotesClient` defines:

- `search_posts_eligible_for_notes(test_mode, max_results, feed_lang, feed_size)`
- `evaluate_note(post_id, note_text)`
- `write_note(post_id, note_text, test_mode, info)`
- `notes_written(since_id, max_results)`
- `get_usage()`

The fixture implementation simulates eligible posts, suggested sources, note request suggestions, evaluator responses, usage, and notes written feedback. The live implementation is selected with `X_PROVIDER=live` and raises unless `ALLOW_LIVE_X_API=true` and a user-context X credential is configured. Live note writing is separately blocked unless `ALLOW_LIVE_X_WRITE=true`.

## Route Mapping

- `POST /api/x/sync-eligible-posts`: calls `posts_eligible_for_notes`.
- `POST /api/drafts/{draft_id}/evaluate-x`: calls `evaluate_note` on the exact current draft text.
- `POST /api/drafts/{draft_id}/submit`: calls `write_note` only after `SubmissionGate` passes.
- `POST /api/notes-written/sync`: calls `notes_written`.
- `GET /api/costs`: reconciles fixture Usage API telemetry against the local cost ledger and returns estimated costs.
- `GET /api/drafts/{draft_id}/export?consent_ack=true`: Track A export. The API rejects export when explicit informed consent is missing.

## Credentials

The local demo never requires credentials. Live credentials are read only from environment variables and are never displayed in `/settings`.

Live provider envs:

- `X_PROVIDER=live`, `ALLOW_LIVE_X_API=true`, `ALLOW_LIVE_X_WRITE=false`
- For a short-lived user-context access token: `X_BEARER_TOKEN=...`
- For refresh support: `X_OAUTH2_CLIENT_ID=...`, optional `X_OAUTH2_CLIENT_SECRET=...`, `X_OAUTH2_REFRESH_TOKEN=...`
- `SEARCH_PROVIDER=brave`, `ALLOW_LIVE_SEARCH=true`, `BRAVE_SEARCH_API_KEY=...`
- `LLM_PROVIDER=openai`, `ALLOW_LIVE_LLM=true`, `OPENAI_API_KEY=...`, `LLM_MODEL=...`

The Community Notes endpoints require X user-context authentication, not an app-only bearer token. Use `X_BEARER_TOKEN` only for a user-context access token. The local helper can generate and refresh user-context credentials:

```bash
export X_OAUTH2_CLIENT_ID=...
export X_OAUTH2_CLIENT_SECRET=... # optional for public clients
export X_OAUTH2_REDIRECT_URI=...
export X_OAUTH2_SCOPES="tweet.read users.read offline.access"

PYTHONPATH=apps/api python3 apps/api/app/cli.py x-oauth-start
PYTHONPATH=apps/api python3 apps/api/app/cli.py x-oauth-exchange CODE CODE_VERIFIER
PYTHONPATH=apps/api python3 apps/api/app/cli.py x-oauth-refresh
```

Required future scopes depend on X's current AI Note Writer API requirements. Confirm exact scopes from X before staging live mode.

## Persistence

Set `PERSISTENCE_PROVIDER=postgres` and `DATABASE_URL` to the Render Postgres internal URL. The app creates `app_records`, a JSONB record store keyed by record type and ID, and persists candidates, raw candidate payloads, claims, sources, evidence cards, drafts, internal scores, X evaluations, submissions, notes-written snapshots, audit events, cost entries, Usage API reconciliation state, and eval runs.

## Test And Live Modes

`test_mode=true` is the default. Non-test writes require:

- `ALLOW_LIVE_X_WRITE=true` when `X_PROVIDER=live`
- `ALLOW_NON_TEST_MODE_WRITE=true`
- explicit operator approval
- Community Notes data-use scope set to `community_notes_ai_note_writing`
- operational evals limited to checks directly necessary to run the note writer
- bot-profile disclosure and responsible-party identity
- exact-text `evaluate_note`
- passing internal critique
- passing cost guard
- admission readiness

## Usage Reconciliation

The Usage API is treated as important telemetry, not the sole billing source. The app keeps a local `CostLedger`, reconciles it with `get_usage()`, tracks whether Developer Console reconciliation is still pending, and surfaces the deduplication soft-guarantee status in `/api/costs`.
