# Community Notes AI Writer Ops Copilot

Fixture-runnable operations copilot for X's AI Note Writer API. The local build runs with no API keys, no live network calls, and no committed secrets. It implements the intake, evidence, drafting, critique, X evaluation, operator approval, submission gate, feedback, admission, writing-limit, cost, governance, and operational eval flows described in `CommunityNotes1.md`, corrected by `CommunityNotes2.md`, and tightened by `CommunityNotes14.md`.

## Quick Start

```bash
cp infra/.env.example .env
make setup
make db-up
make migrate
make seed-fixtures
make dev
```

Open `http://localhost:8000`. The same local server hosts the API and the operator UI.

Run checks:

```bash
make test
make e2e
```

## Local Fixture Flow

1. Sync fixture eligible posts from `/api/x/sync-eligible-posts`.
2. Open a candidate.
3. Run analyze, retrieve, draft, critique, and X evaluate.
4. Approve the exact draft text.
5. Submit in `test_mode=true`.
6. Confirm dashboard, admission, writing-limit, and cost ledger updates.
7. Inspect the candidate governance cards and `/api/governance` for CommunityNotes14 checks.

Track A manual/export mode stays available on the candidate detail page through the export control, but export requires explicit informed contributor consent.

## Stack Notes

The requested production stack is represented in the repo layout, dependency manifests, docs, and deployment guidance:

- `apps/api`: API, schemas, services, X client interface, workers, tests, and migration placeholder.
- `apps/web`: operator UI and browser/E2E fixture workflow.
- `packages/shared`: shared schema contract.
- `packages/evals`: eval fixtures and adversarial cases.
- `infra`: local environment and deployment templates.
- `docs`: architecture, integration, security, eval, deployment, and runbook guidance.

For this empty workspace, the checked-in runtime is dependency-light so it can pass tests and run fixtures immediately without package downloads. The production upgrade path is documented in `docs/DEPLOYMENT.md`.

## Safety Defaults

- Render/Postgres persistence is enabled with `PERSISTENCE_PROVIDER=postgres`; local fixtures default to memory.
- Real providers are opt-in: `X_PROVIDER=live`, `ALLOW_LIVE_X_API=true`, `SEARCH_PROVIDER=brave` with `ALLOW_LIVE_SEARCH=true`, and `LLM_PROVIDER=openai` with `ALLOW_LIVE_LLM=true`.
- Live X calls are disabled unless `ALLOW_LIVE_X_API=true`; live X note writing is separately blocked unless `ALLOW_LIVE_X_WRITE=true`.
- `EMERGENCY_STOP_EXTERNAL_WRITES=true` blocks all external write paths regardless of ordinary gates.
- Non-test writes are additionally blocked unless `ALLOW_NON_TEST_MODE_WRITE=true`, operator approval is present, and readiness checks pass.
- X Community Notes API data scope is constrained to Community Notes AI note writing; operational evals must be directly necessary to run that workflow.
- Track A export requires express informed consent; authentication alone is not treated as consent.
- Track B requires a bot-profile disclosure and responsible-party identity.
- X Usage API telemetry is reconciled with the local cost ledger; Developer Console reconciliation is tracked separately because 24-hour deduplication is a soft guarantee.
- All retrieved text, snippets, suggested links, PDFs, and user inputs are treated as untrusted.
- Every factual sentence in a draft must map to at least one approved evidence `source_id`.
- High-severity hallucination, unsupported claim, weak source, overclaim, harassment/abuse risk, or policy issue blocks submission.
- CommunityNotes14 governance gates cover audience/context, media dependency, high-stakes domains, abstention/redundancy, evidence freshness, evidence reports, cross-perspective helpfulness, writing-opportunity ranking, retention/access control, methodology transparency, policy drift, latency SLO, feed cadence, and official scoring replay.
