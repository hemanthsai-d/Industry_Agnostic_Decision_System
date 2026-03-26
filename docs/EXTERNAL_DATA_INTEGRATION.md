# External Data Integration (ABCD + Twitter Support)

This project now includes a local-first pipeline to turn external conversation datasets into reusable chatbot assets.

## Why these sources

1. ABCD (`asappresearch/abcd`): action-oriented customer dialogues with clear task progression.
2. Customer Support on Twitter (Kaggle `thoughtvector/customer-support-on-twitter`): high-volume, real-world customer phrasing and support replies.

Together they improve:
1. Response style naturalness and personalization.
2. Retrieval corpus breadth for noisy user language.
3. Robustness to social/chat text variation.

## New pipeline

### 1. Build assets from downloaded files

```bash
export ABCD_PATH=/absolute/path/to/abcd.json
export TWITTER_CSV=/absolute/path/to/twcs.csv
make build-chatbot-assets
```

Outputs:
1. `artifacts/datasets/style_examples.jsonl`
2. `artifacts/datasets/retrieval_seed_chunks.jsonl`

### 2. Import retrieval chunks into Postgres

```bash
export POSTGRES_DSN=postgresql://postgres:postgres@127.0.0.1:65432/decision_db
export RETRIEVAL_SEED_JSONL=artifacts/datasets/retrieval_seed_chunks.jsonl
make import-retrieval-seed
```

### 3. Enable generative backend (optional)

```bash
export GENERATION_BACKEND=ollama
export GENERATION_MODEL=qwen2.5:7b-instruct
export GENERATION_OLLAMA_BASE_URL=http://127.0.0.1:11434
make run-api
```

## Runtime safeguards included

1. Anti-copy checks against previous assistant replies.
2. Anti-copy checks against evidence text.
3. Automatic citation enforcement (`[chunk_id]`) in generated responses.
4. Safe escalation fallback when generation is unavailable and fail-open is disabled.

## Notes

1. The pipeline does not automatically download datasets.
2. Inputs should be provided as local files for privacy and reproducibility.
3. Keep dataset usage compliant with source licenses and platform policies.
