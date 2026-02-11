-- Phase 2 migration: add per-collection parser provider
-- Run this on PostgreSQL before deploying code that resolves parser provider from DB collections.

ALTER TABLE iat_collection_types
ADD COLUMN IF NOT EXISTS parser_provider VARCHAR;
