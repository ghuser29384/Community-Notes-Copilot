# Two-Month Community Notes Admission Runbook

**Execution window:** July 18, 2026 through September 17, 2026  
**Cash ceiling:** USD 5,000, excluding ChatGPT and Codex credits  
**Controllable finish line:** a deployed, human-gated writer with a complete 50-note test-mode cohort, correctly ingested evaluator results, reproducible quality evidence, and an admission-ready operating package.

Public non-test note writing is not a completion dependency. X controls enrollment, admission, and any expansion beyond test mode. Keep `ALLOW_NON_TEST_MODE_WRITE=false` throughout this run unless a separate reviewed rollout explicitly changes it.

## Completion criteria

The project is complete when all of the following are true:

1. One genuine X test-mode loop has succeeded: eligible-post retrieval, `evaluate_note`, exact operator approval, note submission, and `notes_written` reconciliation.
2. The deployed service uses durable Postgres persistence, a non-development `SECRET_KEY`, audit records, idempotency, and a tested emergency stop.
3. The most recent 50 test-mode notes have been synchronized and the admission dashboard uses all 50—not a partial window.
4. Official thresholds are met:
   - ClaimOpinion high: at least 30%.
   - ClaimOpinion low: no more than 30%.
   - UrlValidity high: at least 95%.
   - HarassmentAbuse high: at least 98%.
5. Internal stretch targets are reported separately: ClaimOpinion high at least 60%, ClaimOpinion low no more than 10%, and 100% high for URL validity and harassment/abuse.
6. Every factual sentence in the submitted cohort maps to approved evidence, and the independent audit finds zero materially unsupported final assertions.
7. Median eligible-post-to-operator-approved-note latency is no more than ten minutes, with a documented p90 and stage breakdown.
8. A sanitized reproducibility release contains the methodology, cohort metrics, failure taxonomy, latency distribution, budget ledger, and incident/rollback procedure.

## Phase 0: access truth before spending

Do not spend more than **$100** until this phase passes.

### Account prerequisites

- An approved X developer app.
- Enrollment as a Community Notes AI Note Writer.
- Read/write user-context credentials for the enrolled writer account.
- A distinct bot identity and responsible-party disclosure.

X documentation currently presents two user-context authentication paths: the Community Notes quickstart uses OAuth 1.0a, while endpoint reference pages describe OAuth 2.0 user tokens. This application supports both:

- `X_AUTH_MODE=oauth1`: requires `X_API_KEY`, `X_API_KEY_SECRET`, `X_ACCESS_TOKEN`, and `X_ACCESS_TOKEN_SECRET`.
- `X_AUTH_MODE=oauth2`: requires `X_BEARER_TOKEN`, or `X_OAUTH2_CLIENT_ID` plus `X_OAUTH2_REFRESH_TOKEN`.
- `X_AUTH_MODE=auto`: selects complete OAuth 1.0a credentials first, then OAuth 2.0.

For the first live attempt, follow the authentication mode accepted by the enrolled account. Record the mode and the exact successful endpoint set; do not record secrets.

### Safe initial configuration

```dotenv
APP_ENV=production
PERSISTENCE_PROVIDER=postgres
X_PROVIDER=live
X_AUTH_MODE=oauth1
ALLOW_LIVE_X_API=true
ALLOW_LIVE_X_WRITE=false
ALLOW_NON_TEST_MODE_WRITE=false
SEARCH_PROVIDER=fixture
ALLOW_LIVE_SEARCH=false
LLM_PROVIDER=fixture
ALLOW_LIVE_LLM=false
EMERGENCY_STOP_EXTERNAL_WRITES=true
MONTHLY_X_API_BUDGET_USD=150
DAILY_X_API_BUDGET_USD=10
```

Verify `/api/health`, `/api/settings`, `/api/governance`, and `/api/dashboard`. Confirm secrets do not appear in any response or log.

### Read-only smoke

1. Clear the emergency stop only after the deployed configuration has been reviewed.
2. Keep `ALLOW_LIVE_X_WRITE=false`.
3. Call `POST /api/x/sync-eligible-posts` with `{"test_mode": true, "max_results": 1}`.
4. Confirm the candidate is persisted, normalized, and identified by the correct X post ID.
5. Run analyze, retrieve, draft, critique, and X evaluation.
6. Record provider responses, latency, and estimated spend.

### One-write smoke

Enable `ALLOW_LIVE_X_WRITE=true` while keeping `ALLOW_NON_TEST_MODE_WRITE=false`.

Approve the exact draft with explicit X submission metadata:

```json
{
  "classification": "misinformed_or_potentially_misleading",
  "misleading_tags": ["missing_important_context"],
  "operator_override_reason": "Verified note text, source passages, classification, and tags."
}
```

Supported misleading tags are:

- `disputed_claim_as_fact`
- `factual_error`
- `manipulated_media`
- `misinterpreted_satire`
- `missing_important_context`
- `outdated_information`
- `other`

Use `classification=not_misleading` only with an empty tag list. The exact approval hash binds the post ID, text, evidence URLs, classification, tags, test mode, account identity, and gate inputs. A change to any bound field requires reapproval.

Submit exactly one test-mode note, then call `POST /api/notes-written/sync`. Confirm that `ClaimOpinion`, `UrlValidity`, and `HarassmentAbuse` evaluator buckets are stored against the correct note ID. Re-enable the emergency stop after the smoke test while reviewing the evidence.

## Phase 1: first ten notes

Do not spend more than **$500 cumulative** before ten successful test-mode submissions.

For every candidate:

1. Confirm that the central claim is externally checkable and suitable for a note.
2. Reject opinion, sarcasm, duplicates, already-sufficiently-noted posts, and claims without adequate public evidence.
3. Prefer current primary or official sources; use secondary sources only when they add necessary context.
4. Preserve the exact supporting passage, date, jurisdiction, source authority, and URL for every factual sentence.
5. Run contradiction and alternate-explanation searches.
6. Generate multiple concise candidates, but approve only one exact payload.
7. Run X evaluation before approval.
8. Select classification and misleading tags deliberately; do not accept the generic `other` fallback without review.
9. Submit in test mode only.
10. Synchronize evaluator results and classify every failure.

At note ten, stop and issue a go/no-go review covering authentication stability, source quality, evaluator performance, latency, spend, and operator burden.

## Phase 2: 50-note admission cohort

The dashboard must remain ineligible until a full 50-note window exists. Synchronize `notes_written` after every submission or evaluation update. The cohort report must use the most recent 50 test-mode notes.

Pause the run and correct the system when any of these occur:

- a material unsupported statement;
- an inaccessible or invalid source URL;
- an incorrect date, jurisdiction, or unit;
- opinion or speculation in the note;
- classification/tag mismatch;
- duplicate submission attempt;
- unexpected external write;
- daily or monthly budget breach;
- a high-severity policy or abuse result;
- systematic evaluator degradation by topic.

Do not compensate for low quality by increasing volume. The admission cohort is an evidence set, not a throughput target.

## Independent audit

Commission the paid audit only once the live cohort appears capable of meeting thresholds. The reviewer receives:

- original post context;
- final note text;
- approved source passages and URLs;
- date/jurisdiction metadata;
- classification and tags;
- evaluator outcomes.

The reviewer does not need hidden model reasoning. Blind the evaluator scores where practical. Code each note for support, relevance, missing context, neutrality, overclaim, currentness, jurisdiction, URL accessibility, and whether abstention was preferable.

## Budget controls

| Category | Hard cap |
|---|---:|
| X API usage | $300 |
| Deployed model API | $600 |
| Search and document access | $250 |
| Hosting, Postgres, monitoring, backups, domain | $300 |
| Independent factual-quality audit | $1,500 |
| Targeted legal/policy review | $750 |
| Contingency | $1,000 |
| **Total** | **$4,700** |

Operational controls:

- Configure provider-side spending limits in addition to application estimates.
- Record actual invoices separately from estimated ledger entries.
- Reconcile X usage API data and the developer console.
- Use ChatGPT/Codex for offline development and replay work where permitted; reserve deployed API calls for the operating workflow.
- Do not purchase enterprise hosting, a frontend rewrite, a vector database, or large news feeds without measured necessity.
- Restrict the first cohort to English-language, primarily textual claims. Media-dependent claims remain held unless an approved multimodal workflow is explicitly enabled and audited.

## Weekly deliverables

### Week 1

- Access and authentication decision recorded.
- Deployed read-only service.
- One genuine test-mode loop completed or a precise external-access blocker documented.

### Week 2

- Production persistence, backups, observability, emergency-stop drill, and exact-payload approval verified.
- First ten-note gate opened only after the access smoke succeeds.

### Weeks 3–4

- Retrieval/source-authority improvements.
- Historical and adversarial replay set.
- Latency instrumentation and operator workflow refinement.

### Week 5

- Fifty-note test-mode run completed or paused under a documented quality stop.

### Week 6

- Blind factual audit.
- Error taxonomy, calibration, and latency optimization.

### Weeks 7–8

- Conservative operating pilot if access permits.
- Reproducibility package, budget reconciliation, incident runbook, and handoff.

## Rollback

Set and redeploy:

```dotenv
ALLOW_LIVE_X_API=false
ALLOW_LIVE_X_WRITE=false
ALLOW_NON_TEST_MODE_WRITE=false
SEARCH_PROVIDER=fixture
ALLOW_LIVE_SEARCH=false
LLM_PROVIDER=fixture
ALLOW_LIVE_LLM=false
EMERGENCY_STOP_EXTERNAL_WRITES=true
```

Then verify `/api/governance` reports blocked external writes. Preserve audit records and the last known-good database; do not delete evidence required to investigate an incident unless retention policy or platform terms require deletion.
