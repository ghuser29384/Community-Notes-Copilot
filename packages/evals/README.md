# Offline Evals

The eval package contains fixture and adversarial cases used by `/api/evals/run` and `make test`.

Covered checks:

- Strict schema handling for fixture LLM outputs.
- Prompt injection text remains untrusted.
- Unsupported factual sentences block submission.
- High-severity critique issues block submission.
- Fixture Track B flow reaches only `test_mode=true` submission by default.
- Overbroad Community Notes API data use blocks submission.
- Missing Track B bot identity blocks submission.
- Track A manual/export mode requires express and informed contributor consent.
- Writing-limit telemetry exposes official terms including `WL`, `NH_5`, `NH_10`, `HR_R`, `HR_100`, `HR_14d`, `HR_L`, `DN_30`, and `T`.
- Cost telemetry reconciles the local ledger with Usage API snapshots and keeps Developer Console reconciliation separate.

Add a fixture by creating a JSON file under `fixtures/` with candidate context, suggested sources, claims, evidence, draft text, expected gate status, and evaluator scores.
