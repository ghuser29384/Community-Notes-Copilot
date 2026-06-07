# Security And Policy

## Non-Negotiable Defaults

- Do not train or fine-tune a foundation/frontier model on X API data or X Content.
- Do not submit unless `SubmissionGate` passes.
- Live X calls are disabled by default.
- Live X note writing is disabled behind a separate `ALLOW_LIVE_X_WRITE` flag.
- `EMERGENCY_STOP_EXTERNAL_WRITES=true` blocks all fixture and live write paths regardless of ordinary gates.
- Live search and live LLM calls are disabled by default.
- Non-test writes are disabled by default.
- Operator approval is required by default.
- Process X Community Notes API data solely for Community Notes AI note writing.
- Run evaluation only when directly necessary to operate that note-writing workflow.
- Track A manual/export actions require express and informed contributor consent; authentication alone is not enough.
- Track B API-based bot use requires bot-profile disclosure and a responsible-party identity.
- Every factual sentence in a draft note must map to approved evidence source IDs.
- High-severity hallucination, unsupported claim, weak source, overclaim, harassment/abuse risk, or policy issue blocks submission.
- Media-dependent claims require an approved multimodal workflow or operator hold/abstention.
- High-stakes health, civic, legal, financial, public-safety, war/crisis, and identity-sensitive claims require authoritative/current evidence and operator confirmation.
- Cross-perspective helpfulness, writing-opportunity priority, freshness, audience/context fit, and abstention/redundancy checks must pass before submission.

## Prompt Injection

Retrieved webpages, post text, suggested links, PDFs, snippets, and user inputs are treated as untrusted. The eval fixture `packages/evals/adversarial/prompt_injection.json` verifies that hostile text cannot bypass approval or schema requirements.

## Secrets

Secrets live in environment variables only. `/api/settings` exposes only booleans, provider names, budgets, and thresholds. It never returns tokens or key material.

## Data Use Scope

`COMMUNITY_NOTES_DATA_USE_PURPOSE` must remain `community_notes_ai_note_writing`. The implementation treats broader phrases such as `api_note_writing_operations_and_local_evaluation` as over-broad and blocks submission. `OPERATIONAL_EVALS_DIRECTLY_NECESSARY=true` means evals are limited to quality, safety, and operations checks directly necessary for running the note writer.

## Consent And Bot Identity

Track A export requires `consent_ack=true` at the API layer and a UI checkbox before copying/exporting draft text. The export artifact records the consent actor and reason.

Track B requires `BOT_PROFILE_DISCLOSURE` and `BOT_RESPONSIBLE_PARTY`. The submission gate checks both before any API submission, including fixture test-mode submissions.

## Duplicate And Spam Controls

Candidate normalization computes `canonical_hash` from the full `note_tweet` text when present plus referenced, quoted, and replied-to context to deduplicate intake. The gate blocks statuses including `DUPLICATE`, `ALREADY_HAS_MATCHED_SHOWN_NOTE`, `NO_NOTE`, `HELD_FOR_OPERATOR`, and `BLOCKED`.

## CommunityNotes14 Governance

The governance layer persists candidate and draft decisions for:

- Portable context schema and platform adapter output.
- Audience/context sensitivity.
- Media-dependency classification.
- High-stakes domain routing.
- Abstention and redundancy.
- Evidence freshness and post-submission lifecycle monitoring.
- Linkable evidence reports with public redactions.
- Cross-perspective helpfulness.
- Writing-opportunity ranking.
- Retention/access-control classification.
- Methodology transparency, policy drift, emergency stop, latency SLO, feed strategy, and official scoring replay status.

The public-safe summary is available at `/api/governance`. It must not expose credentials, private X payloads, exact exploitable thresholds, or operator identifiers.

## Cost And Rate Limits

Every fixture X call logs an estimated cost. `CostLedger` blocks submission when daily or monthly budgets are exceeded.

The local ledger is reconciled against fixture `get_usage()` output that models X Usage API telemetry. Developer Console reconciliation is represented as a separate tracked status because pricing and 24-hour deduplication should be treated as soft operational telemetry, not a sole source of truth.

## Provider Gates

Real providers are opt-in and independently gated. `X_PROVIDER=live` still cannot call X unless `ALLOW_LIVE_X_API=true` and credentials are present, and it cannot call `write_note` unless `ALLOW_LIVE_X_WRITE=true`. `SEARCH_PROVIDER=brave` requires `ALLOW_LIVE_SEARCH=true`. `LLM_PROVIDER=openai` requires `ALLOW_LIVE_LLM=true`, `OPENAI_API_KEY`, and `LLM_MODEL`. Keep `ALLOW_LIVE_X_WRITE=false` and `ALLOW_NON_TEST_MODE_WRITE=false` until Postgres persistence, read-only X calls, cost reconciliation, and operator workflows are verified.

## External Sharing

Prefer IDs and rehydration over redistributing full X content externally where practical. This is implemented as a compliance-minded default, not as a universal explicit rule.
