-- Phase 12 migration: prompt tool policy
-- Adds a JSONB container for per-prompt tool selection policy.

ALTER TABLE iatoolkit.iat_prompt
ADD COLUMN IF NOT EXISTS tool_policy JSONB NOT NULL DEFAULT '{"mode":"inherit","tool_names":[]}'::jsonb;
