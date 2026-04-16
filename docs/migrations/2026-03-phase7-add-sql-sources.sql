-- Core migration: canonical SQL source catalog
-- Runtime SQL registrations should resolve from this table.

CREATE TABLE IF NOT EXISTS iatoolkit.iat_sql_sources (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES iatoolkit.iat_companies(id) ON DELETE CASCADE,

    database VARCHAR(255) NOT NULL,
    connection_type VARCHAR(32) NOT NULL DEFAULT 'direct',
    connection_string_env VARCHAR(255),
    schema VARCHAR(255) NOT NULL DEFAULT 'public',
    description TEXT,
    bridge_id VARCHAR(255),

    source VARCHAR(16) NOT NULL DEFAULT 'YAML',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),

    CONSTRAINT uix_company_sql_source_database UNIQUE (company_id, database)
);

CREATE INDEX IF NOT EXISTS idx_iat_sql_sources_company
    ON iatoolkit.iat_sql_sources(company_id);

CREATE INDEX IF NOT EXISTS idx_iat_sql_sources_active
    ON iatoolkit.iat_sql_sources(is_active);

CREATE INDEX IF NOT EXISTS idx_iat_sql_sources_source
    ON iatoolkit.iat_sql_sources(source);
