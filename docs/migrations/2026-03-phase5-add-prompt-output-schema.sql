-- Phase 5 migration: add prompt output schema persistence
-- Run this on PostgreSQL before deploying code that persists prompt response contracts.

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS output_schema JSONB;

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS output_schema_yaml TEXT;

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS output_schema_mode VARCHAR(32) NOT NULL DEFAULT 'best_effort';

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS output_response_mode VARCHAR(32) NOT NULL DEFAULT 'chat_compatible';
