CREATE TABLE IF NOT EXISTS iatoolkit.iat_knowledge_wikis (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES iatoolkit.iat_companies(id) ON DELETE CASCADE,
    wiki_key VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description TEXT NULL,
    root_storage_key VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'published',
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_knowledge_wiki_company_key UNIQUE (company_id, wiki_key)
);

CREATE TABLE IF NOT EXISTS iatoolkit.iat_knowledge_wiki_pages (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES iatoolkit.iat_companies(id) ON DELETE CASCADE,
    wiki_id INTEGER NOT NULL REFERENCES iatoolkit.iat_knowledge_wikis(id) ON DELETE CASCADE,
    path VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    summary TEXT NULL,
    body_text TEXT NULL,
    source_storage_key VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'published',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner VARCHAR NULL,
    source_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uix_knowledge_wiki_page_path UNIQUE (wiki_id, path),
    CONSTRAINT uix_knowledge_wiki_page_slug UNIQUE (wiki_id, slug)
);

CREATE TABLE IF NOT EXISTS iatoolkit.iat_knowledge_wiki_sync_runs (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES iatoolkit.iat_companies(id) ON DELETE CASCADE,
    wiki_id INTEGER NOT NULL REFERENCES iatoolkit.iat_knowledge_wikis(id) ON DELETE CASCADE,
    status VARCHAR NOT NULL DEFAULT 'running',
    pages_seen INTEGER NOT NULL DEFAULT 0,
    pages_indexed INTEGER NOT NULL DEFAULT 0,
    pages_failed INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_knowledge_wikis_company_status
    ON iatoolkit.iat_knowledge_wikis(company_id, status);

CREATE INDEX IF NOT EXISTS ix_knowledge_wiki_pages_company_wiki_status
    ON iatoolkit.iat_knowledge_wiki_pages(company_id, wiki_id, status);

CREATE INDEX IF NOT EXISTS ix_knowledge_wiki_pages_source_storage_key
    ON iatoolkit.iat_knowledge_wiki_pages(source_storage_key);

CREATE INDEX IF NOT EXISTS ix_knowledge_wiki_sync_runs_wiki_status
    ON iatoolkit.iat_knowledge_wiki_sync_runs(wiki_id, status);
