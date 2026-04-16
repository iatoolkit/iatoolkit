-- Phase 6 migration: prompt attachment delivery policy
-- Run this on PostgreSQL before deploying code that persists attachment policy.

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS attachment_mode VARCHAR(32) NOT NULL DEFAULT 'extracted_only';

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS attachment_fallback VARCHAR(32) NOT NULL DEFAULT 'extract';
