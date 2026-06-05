# API Integration

## X Client Methods

`XCommunityNotesClient` defines:

- `search_posts_eligible_for_notes(test_mode, max_results, feed_lang, feed_size)`
- `evaluate_note(post_id, note_text)`
- `write_note(post_id, note_text, test_mode, info)`
- `notes_written(since_id, max_results)`
- `get_usage()`

The fixture implementation simulates eligible posts, suggested sources, note request suggestions, evaluator responses, usage, and notes written feedback. The live implementation raises unless `ALLOW_LIVE_X_API=true`.

## Route Mapping

- `POST /api/x/sync-eligible-posts`: calls `posts_eligible_for_notes`.
- `POST /api/drafts/{draft_id}/evaluate-x`: calls `evaluate_note` on the exact current draft text.
- `POST /api/drafts/{draft_id}/submit`: calls `write_note` only after `SubmissionGate` passes.
- `POST /api/notes-written/sync`: calls `notes_written`.
- `GET /api/costs`: reconciles fixture Usage API telemetry against the local cost ledger and returns estimated costs.
- `GET /api/drafts/{draft_id}/export?consent_ack=true`: Track A export. The API rejects export when explicit informed consent is missing.

## Credentials

The local demo never requires credentials. Live credentials are read only from environment variables and are never displayed in `/settings`.

Required future scopes depend on X's current AI Note Writer API requirements. Confirm exact scopes from X before staging live mode.

## Test And Live Modes

`test_mode=true` is the default. Non-test writes require:

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
