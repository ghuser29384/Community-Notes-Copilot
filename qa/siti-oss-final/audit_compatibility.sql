-- AUDIT-ONLY COMPATIBILITY MIGRATION
--
-- Purpose: make the exact public legacy server commit
--   933f345801340027181be21d24671146e3785701
-- runnable against the exact public schema commit
--   091229bff2a299c31b814979008ebc6df7b428e8
-- in an isolated test database.
--
-- This file is not asserted to represent the production schema and must not be
-- applied to production. Each addition is limited to an object referenced by
-- the audited public server source but absent from the audited public schema,
-- plus one generated alias used only to make evidence queries deterministic.

BEGIN;

ALTER TABLE grasp.cards
  ADD COLUMN IF NOT EXISTS network_data jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE grasp.reports
  ADD COLUMN IF NOT EXISTS partner_code varchar;

ALTER TABLE cognicity.all_reports
  ADD COLUMN IF NOT EXISTS partner_code varchar;

-- The public grasp push function stores the one-time card UUID in all_reports.url.
-- Expose a generated test-only alias so regression evidence can count the
-- normalized row without changing the audited server's write path.
ALTER TABLE cognicity.all_reports
  ADD COLUMN IF NOT EXISTS card_id varchar
  GENERATED ALWAYS AS (
    CASE WHEN source = 'grasp' THEN url ELSE NULL END
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_audit_all_reports_card_id
  ON cognicity.all_reports(card_id)
  WHERE card_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS cognicity.partners (
  id bigserial PRIMARY KEY,
  partner_code varchar NOT NULL UNIQUE,
  partner_name varchar NOT NULL,
  partner_status boolean NOT NULL DEFAULT true,
  partner_icon varchar
);

COMMENT ON TABLE cognicity.partners IS
  'Audit-only compatibility object: referenced by public server commit but absent from public schema commit.';

COMMENT ON COLUMN cognicity.all_reports.card_id IS
  'Audit-only generated alias of url for source=grasp; not a production-schema claim.';

COMMIT;
