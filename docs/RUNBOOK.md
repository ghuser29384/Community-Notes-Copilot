# Runbook

## Budget Cap Breach

1. Set `ALLOW_LIVE_X_API=false`.
2. Confirm `/api/costs` local ledger daily and monthly totals.
3. Confirm the latest Usage API snapshot and treat 24-hour deduplication as a soft guarantee, not the only source of truth.
4. Check the Developer Console separately before raising budgets.
5. Review recent `CostLedgerEntry` actions.
6. Lower `DAILY_X_API_BUDGET_USD` or provider budgets if needed.

## Policy Scope Regression

1. Keep `ALLOW_NON_TEST_MODE_WRITE=false`.
2. Confirm `/api/settings` reports `community_notes_ai_note_writing` and directly necessary operational evals.
3. Confirm bot-profile disclosure and responsible-party identity are configured.
4. Confirm Track A manual/export workflows require express and informed contributor consent.
5. Re-run fixture E2E and offline evals before restoring any live read-only API path.

## Persistence Regression

1. Confirm `/api/health` reports `persistence_provider` as `postgres`.
2. Sync fixtures, create a draft, then manually redeploy or restart the Render service.
3. Reopen the UI and confirm the candidate, draft, audit events, and cost entries remain.
4. If state disappears, verify `PERSISTENCE_PROVIDER=postgres`, `DATABASE_URL`, and the Render build command installs `requirements.txt`.

## Low Evaluator Scores

1. Open `/admission`.
2. Review ClaimOpinion, UrlValidity, and HarassmentAbuse blockers.
3. Inspect recent drafts and support maps.
4. Roll back prompt versions if unsupported or overclaimed notes appear.

## Admission Regression

1. Keep `ALLOW_NON_TEST_MODE_WRITE=false`.
2. Run `/api/evals/run`.
3. Audit low-scoring notes from `notes_written`.
4. Tighten `InternalCritic` or evidence thresholds.

## API Failure

1. Confirm `/api/health`.
2. Switch providers to fixture: `X_PROVIDER=fixture`, `SEARCH_PROVIDER=fixture`, `LLM_PROVIDER=fixture`, and set live flags false.
3. Retry `POST /api/x/sync-eligible-posts`.
4. Check env flags and X credentials in the deployment secret store.

## Prompt Rollback

1. Mark the current prompt version as blocked in the production database.
2. Revert to the previous prompt version.
3. Run offline evals.
4. Resume only test-mode submissions until scores recover.
