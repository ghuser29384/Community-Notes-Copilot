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
-- the audited public server source but absent from the audited public schema.

BEGIN;

ALTER TABLE grasp.cards
  ADD COLUMN IF NOT EXISTS network_data jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE grasp.reports
  ADD COLUMN IF NOT EXISTS partner_code varchar;

ALTER TABLE cognicity.all_reports
  ADD COLUMN IF NOT EXISTS partner_code varchar;

CREATE TABLE IF NOT EXISTS cognicity.partners (
  id bigserial PRIMARY KEY,
  partner_code varchar NOT NULL UNIQUE,
  partner_name varchar NOT NULL,
  partner_status boolean NOT NULL DEFAULT true,
  partner_icon varchar
);

COMMENT ON TABLE cognicity.partners IS
  'Audit-only compatibility object: referenced by public server commit but absent from public schema commit.';

COMMIT;
