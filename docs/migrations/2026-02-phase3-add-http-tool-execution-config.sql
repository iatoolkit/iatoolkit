-- Phase 3 migration: add HTTP tool execution config storage
-- Run this on PostgreSQL before deploying code that persists HTTP tool configuration.

ALTER TABLE iatoolkit.iat_tools
ADD COLUMN IF NOT EXISTS execution_config JSONB;
