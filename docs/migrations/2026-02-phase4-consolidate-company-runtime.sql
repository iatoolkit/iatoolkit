-- Phase 4: consolidate company runtime status in iat_companies
-- Safe to run multiple times on PostgreSQL.

ALTER TABLE iatoolkit.iat_companies
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN;

ALTER TABLE iatoolkit.iat_companies
    ADD COLUMN IF NOT EXISTS runtime_mode VARCHAR(32);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'iatoolkit'
          AND table_name = 'iat_company_deployments'
    ) THEN
        UPDATE iatoolkit.iat_companies c
        SET
            is_active = COALESCE(d.is_active, c.is_active),
            runtime_mode = COALESCE(NULLIF(LOWER(TRIM(CAST(d.runtime_mode AS TEXT))), ''), c.runtime_mode)
        FROM iatoolkit.iat_company_deployments d
        WHERE d.company_id = c.id;
    END IF;
END$$;

UPDATE iatoolkit.iat_companies
SET is_active = COALESCE(is_active, TRUE);

UPDATE iatoolkit.iat_companies
SET runtime_mode = COALESCE(NULLIF(LOWER(TRIM(runtime_mode)), ''), 'static');

ALTER TABLE iatoolkit.iat_companies
    ALTER COLUMN is_active SET NOT NULL;

ALTER TABLE iatoolkit.iat_companies
    ALTER COLUMN is_active SET DEFAULT TRUE;

ALTER TABLE iatoolkit.iat_companies
    ALTER COLUMN runtime_mode SET NOT NULL;

ALTER TABLE iatoolkit.iat_companies
    ALTER COLUMN runtime_mode SET DEFAULT 'static';

CREATE INDEX IF NOT EXISTS idx_iat_companies_is_active
    ON iatoolkit.iat_companies(is_active);

CREATE INDEX IF NOT EXISTS idx_iat_companies_runtime_mode
    ON iatoolkit.iat_companies(runtime_mode);

ALTER TABLE iatoolkit.iat_companies
    DROP COLUMN IF EXISTS company_class_ref;
