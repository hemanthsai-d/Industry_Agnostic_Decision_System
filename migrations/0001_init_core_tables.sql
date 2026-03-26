CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc_chunks (
  chunk_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  section TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  source TEXT NOT NULL,
  updated_at DATE NOT NULL,
  text_content TEXT NOT NULL,
  embedding VECTOR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_tenant_section
  ON doc_chunks (tenant_id, section);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_fts
  ON doc_chunks USING GIN (to_tsvector('english', text_content));

CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding
  ON doc_chunks USING hnsw (embedding vector_cosine_ops);

