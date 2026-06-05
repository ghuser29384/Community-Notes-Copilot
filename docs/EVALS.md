# Evals

## Local Commands

```bash
make test
make e2e
```

`make test` uses Python unittest in this dependency-light runtime. Production should add pytest/respx and Playwright once dependencies are installed.

Eval scope is intentionally narrow: run only quality, grounding, safety, and regression checks directly necessary to operate the Community Notes AI note writer. Do not treat evals as a separate permitted use of X API/X Content.

## Metrics

Admission readiness uses the rolling 50-note thresholds:

- ClaimOpinion high >= 30%
- ClaimOpinion low <= 30%
- UrlValidity high >= 95%
- HarassmentAbuse high >= 98%

Writing-limit monitoring displays:

- `WL`
- `NH_5`
- `NH_10`
- `HR_R`
- `HR_100`
- `HR_14d`
- `HR_L`
- `DN_30`
- `T`
- total notes
- estimated writing limit
- feed-size eligibility, including non-test-mode-only `large`, `xl`, and `xxl`
- 90-day writing impact
- `test_result` and `scoring_status` raw counts

The UI shows formulas and raw inputs instead of hiding them.

## Adding Cases

Add fixtures under `packages/evals/fixtures` and adversarial cases under `packages/evals/adversarial`. Include expected claim status, evidence outcome, draft status, gate result, and evaluator scores.
