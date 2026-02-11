-- Phase 2 migration: remove deprecated iat_documents.content column
-- Run this on PostgreSQL before deploying the phase 2 code.

ALTER TABLE iat_documents
DROP COLUMN IF EXISTS content;
