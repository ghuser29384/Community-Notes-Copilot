# Runbook

## Budget Cap Breach

Immediate: set `EMERGENCY_STOP_EXTERNAL_WRITES=true` if any write path might still be active.
1. Set `ALLOW_LIVE_X_API=false`.
2. Set `ALLOW_LIVE_X_WRITE=false`.
3. Confirm `/api/costs` local ledger daily and monthly totals.
4. Confirm the latest Usage API snapshot and treat 24-hour deduplication as a soft guarantee, not the only source of truth.
5. Check the Developer Console separately before raising budgets.
6. Review recent `CostLedgerEntry` actions.
7. Lower `DAILY_X_API_BUDGET_USD` or provider budgets if needed.

## Policy Scope Regression

Immediate: set `EMERGENCY_STOP_EXTERNAL_WRITES=true` for material policy or documentation drift.
1. Keep `ALLOW_NON_TEST_MODE_WRITE=false`.
2. Confirm `/api/settings` reports `community_notes_ai_note_writing` and directly necessary operational evals.
3. Confirm bot-profile disclosure and responsible-party identity are configured.
4. Confirm Track A manual/export workflows require express and informed contributor consent.
5. Confirm `/api/governance` reports the methodology, policy drift status, emergency-stop state, and official scoring replay status.
6. Re-run fixture E2E and offline evals before restoring any live read-only API path.

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

Immediate: set `EMERGENCY_STOP_EXTERNAL_WRITES=true` if API behavior is unknown.
1. Confirm `/api/health`.
2. Switch providers to fixture: `X_PROVIDER=fixture`, `SEARCH_PROVIDER=fixture`, `LLM_PROVIDER=fixture`, and set live flags false, including `ALLOW_LIVE_X_WRITE=false`.
3. Retry `POST /api/x/sync-eligible-posts`.
4. Check env flags and X credentials in the deployment secret store.

## Prompt Rollback

Immediate: set `EMERGENCY_STOP_EXTERNAL_WRITES=true`.
1. Mark the current prompt version as blocked in the production database.
2. Revert to the previous prompt version.
3. Run offline evals.
4. Resume only test-mode submissions until scores recover.

## CommunityNotes14 Governance Hold

1. Open the candidate detail view and inspect Audience, Media dependency, High-stakes routing, Abstention/redundancy, Freshness lifecycle, and Retention/access.
2. For media-dependent holds, keep `APPROVED_MULTIMODAL_WORKFLOW_ENABLED=false` unless a reviewed multimodal workflow exists; resolve by operator review or abstain.
3. For high-stakes holds, require authoritative/current sources, jurisdiction or audience context, and operator confirmation.
4. For freshness holds, re-retrieve or replace sources and verify source dates, correction/retraction status, and currentness.
5. For redundancy holds, check local submissions, public notes, semantic duplicate flags, and recent draft history before overriding.
6. Re-run Critique, Evaluate X, and Submit test only after the governance cards show pass/allow-now states.

## Emergency Stop Re-Enablement

1. Record incident trigger, severity, response actions, and affected candidates/submissions.
2. Rotate credentials if credential exposure or prompt-injection escalation is suspected.
3. Roll back prompt, gate, adapter, or source-policy versions if needed.
4. Run `make test`, `make lint`, `make e2e`, and `/api/evals/run`.
5. Confirm `/api/governance` shows no material policy drift review tasks.
6. Set `EMERGENCY_STOP_EXTERNAL_WRITES=false` only after explicit operator approval.
