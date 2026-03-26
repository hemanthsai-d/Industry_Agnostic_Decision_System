<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115.6-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/PostgreSQL-16+pgvector-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL"/>
  <img src="https://img.shields.io/badge/Redis-7-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis"/>
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/Kubernetes-Helm-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="Kubernetes"/>
  <img src="https://img.shields.io/badge/Prometheus-Grafana-E6522C?style=for-the-badge&logo=prometheus&logoColor=white" alt="Observability"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License"/>
</p>

<h1 align="center">🧠 Decision Platform</h1>

<p align="center">
  <strong>An industry-agnostic, production-grade AI decision engine for agent-assist customer support triage.</strong><br/>
  Classify intent · Retrieve evidence · Score confidence · Apply policy gates · Generate grounded responses · Escalate to humans when uncertain.
</p>

---

## Table of Contents

| # | Section | Description |
|---|---------|-------------|
| 1 | [What Is This?](#1-what-is-this) | Platform overview and problem statement |
| 2 | [Why This Platform? — Novelty](#2-why-this-platform--novelty) | What makes this unique |
| 3 | [System Architecture](#3-system-architecture) | High-level architecture diagram |
| 4 | [Request Lifecycle](#4-request-lifecycle--the-full-pipeline) | End-to-end request flow |
| 5 | [Data Architecture](#5-data-architecture) | Database schema, storage, and data flow |
| 6 | [Data Transformation Pipeline](#6-data-transformation-pipeline) | What, how, when, why for every transformation |
| 7 | [ML / AI Pipeline](#7-ml--ai-pipeline) | Routing, embeddings, generation, calibration |
| 8 | [Security Architecture](#8-security-architecture) | Auth, rate limiting, PII, prompt injection |
| 9 | [Observability Stack](#9-observability-stack) | Metrics, tracing, alerting, dashboards |
| 10 | [Infrastructure & Deployment](#10-infrastructure--deployment) | Docker, Kubernetes, Helm, CI/CD |
| 11 | [API Reference](#11-api-reference) | All endpoints and schemas |
| 12 | [Configuration Reference](#12-configuration-reference) | Every setting explained |
| 13 | [Getting Started](#13-getting-started) | Setup, run, first request |
| 14 | [Project Structure](#14-project-structure) | Full directory tree |
| 15 | [Makefile Commands](#15-makefile-commands) | All available commands |

---

## 1. What Is This?

The **Decision Platform** is a full-stack AI decision engine designed for customer-support triage. Given a customer issue, it:

1. **Classifies** the intent using ML routing models (30 intent categories)
2. **Retrieves** relevant evidence via hybrid search (sparse + dense + fusion)
3. **Scores** confidence using a multi-signal calibrated formula
4. **Applies** policy gates (OPA or local rules) to decide: **recommend**, **abstain**, or **escalate**
5. **Generates** a grounded response (template or LLM) with anti-copy enforcement
6. **Escalates** uncertain or high-risk decisions to human reviewers with full context
7. **Learns** from human feedback to continuously improve

### The Problem

Customer support teams face a critical challenge: automated systems must know **when to act** and **when to defer to humans**. Most AI systems either over-automate (causing errors on edge cases) or under-automate (wasting human capacity on routine tasks). This platform solves the **calibrated decision boundary problem** — it does not just classify; it quantifies uncertainty across multiple dimensions and makes principled decide-or-defer choices.

### The Solution

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        DECISION PLATFORM                                 │
│                                                                          │
│   Customer    ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐    │
│   Issue  ───▶ │ Classify │──▶│ Retrieve │──▶│  Score   │──▶│ Decide │    │
│               │ Intent   │   │ Evidence │   │Confidence│   │ Policy │    │
│               └─────────┘   └──────────┘   └──────────┘   └────┬────┘    │
│                                                                │         │
│                    ┌─────────────────┬───────────────────┐     │         │
│                    ▼                 ▼                   ▼     │         │
│              ┌──────────┐    ┌────────────┐    ┌──────────┐    │         │
│              │ RECOMMEN │    │ ABSTAIN    │    │ ESCALATE │    │         │
│              │ Generate │    │  Handoff   │    │ Handoff  │    │         │
│              │ Response │    │ to Human   │    │ to Human │    │         │
│              └──────────┘    └────────────┘    └──────────┘    │         │
│                                                                │         │
│              ┌──────────────────────────────────────────────┐  │         │
│              │   Persist  ·  Publish Events  ·  Learn       │◀──┘        │
│              └──────────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Category | Technologies |
|----------|-------------|
| **Runtime** | Python 3.13 · FastAPI 0.115.6 · Uvicorn · Pydantic 2 |
| **Data** | PostgreSQL 16 + pgvector · Redis 7 |
| **ML / AI** | Sentence-Transformers (all-MiniLM-L6-v2) · Ollama (qwen2.5:7b-instruct) |
| **Policy** | Open Policy Agent (OPA) 0.69.0 · Rego |
| **Security** | PyJWT · RBAC · PII Redaction · Prompt Injection Defense |
| **Observability** | Prometheus · Grafana 11.2.2 · Alertmanager 0.28.0 · Jaeger 1.60 · OpenTelemetry |
| **Integrations** | Google Cloud Pub/Sub · Temporal · Model Context Protocol (MCP) · HashiCorp Vault |
| **Infrastructure** | Docker Compose · Kubernetes (kind / cloud) · Helm · GitHub Actions CI/CD |

---

## 2. Why This Platform? — Novelty

### What Is Transforming, How, Why, and When

| # | Innovation | What Is Changing | How It Transforms | Why It Matters | When It Activates |
|---|-----------|-----------------|-------------------|----------------|-------------------|
| 🔬 | **Multi-Signal Confidence** | Single model probability → 5-signal fused confidence score | Combines route probability, evidence quality, escalation risk, OOD detection, and contradiction scores using calibrated weights | Most systems use only model confidence. Fusing 5 independent signals produces more reliable decide/defer boundaries | Every `/v1/assist/decide` request |
| 🔄 | **Complete ML Lifecycle** | External ML platform dependency → zero-dependency in-codebase lifecycle | Shadow evaluation → canary split → quality gates → automated promotion with full lineage tracking | No external MLOps tooling needed. Full audit trail from development through production | When `MODEL_SHADOW_ENABLED=true` or `CANARY_ROLLOUT_ENABLED=true` |
| 🛡️ | **3-Layer Prompt Injection Defense** | Simple keyword blocklist → multi-layer statistical defense | 18 regex rules + role marker analysis + character entropy scoring at input, plus output validation post-generation | Defense-in-depth against adversarial manipulation of LLM behavior | Every request when `PROMPT_INJECTION_ENABLED=true` |
| 📚 | **Hybrid Retrieval + Staleness Decay** | Single-mode search → hybrid sparse+dense with time-aware ranking | FTS + pgvector cosine + RRF fusion + cross-encoder reranking + dedup + time-decay penalties, all within PostgreSQL | No external vector database. Evidence freshness is automatically weighted. Covers both keyword and semantic retrieval | Every evidence retrieval step |
| 🎯 | **Deterministic Canary Bucketing** | Random traffic split → deterministic SHA-256 hash bucketing | SHA-256 of `tenant_id:request_id` mod 100 < canary_percent → reproducible, debuggable traffic splits | Same request always routes to same model variant. No external feature flag service needed | When canary rollout is active |
| ✍️ | **Anti-Copy Enforcement** | Unchecked LLM output → triple-checked originality | Token-set Jaccard + 4-gram overlap + per-evidence similarity on every generated response, with retry on failure | Ensures responses are original paraphrases, not verbatim copies of training data or evidence | Every response generation step |
| 🔁 | **Ground-Truth Feedback Loop** | One-way inference → closed learning loop | Handoff closure requires `reviewer_id` + `final_decision` + `final_resolution_path`, mirrored back to evaluation tables | Human corrections directly improve future model evaluations. Learning loop is structurally enforced | When handoffs are closed via `PATCH /v1/assist/handoffs/{id}/status` |
| 🤖 | **MCP Server** | API-only access → AI assistant tool integration | Exposes the entire decision pipeline as tool calls via the Model Context Protocol (stdio transport) | AI assistants (Claude, Copilot, etc.) can invoke the decision engine as an agentic tool | When MCP server is running |
| 📊 | **25+ Metrics · 14 Alerts** | Basic logging → production-grade observability | Per-stage pipeline latency, RAG faithfulness, hallucination ratio, cost-per-request, circuit breaker state, drift detection | Observability from day one, not bolted on. Every failure mode has a corresponding alert | Always when `METRICS_ENABLED=true` |
| 🚀 | **Zero-Dependency Dev Mode** | Docker-required development → instant local startup | In-memory stores, heuristic routing, template generation, noop event bus — everything works without Docker | `make run-api` with zero external dependencies for rapid development | When `USE_POSTGRES=false` and `USE_REDIS=false` |
| 📱 | **Channel-Aware Generation** | One-size-fits-all responses → channel-optimized outputs | Different prompt constraints per channel: Twitter 280 chars, chat 600, email 1500, phone 800 | Generated responses respect the medium. Matches real-world agent workflows | When `GENERATION_BACKEND=ollama` and `context.channel` is set |
| 🏥 | **Production Config Hardening** | Trust-the-deployer → enforce-at-startup validation | Validators block weak DB passwords, disabled auth, local-only embeddings, and disabled PII redaction in production | Impossible to accidentally deploy an insecure configuration. Fails fast at startup | When `APP_ENV=production` |

---

## 3. System Architecture

### 3.1 High-Level Architecture

```mermaid
graph TB
    subgraph External["🌐 External"]
        Client["Client Application"]
        LB["Cloud Load Balancer<br/><i>TLS 1.3</i>"]
    end

    subgraph Ingress["🚪 Ingress Layer"]
        NGINX["nginx-ingress<br/><i>Rate limit: 1k RPS</i>"]
    end

    subgraph API["⚡ API Layer — FastAPI Port 8000"]
        Auth["JWT Auth + RBAC"]
        RateLimit["Redis Rate Limiter<br/><i>Token Bucket</i>"]
    end

    subgraph Core["🧠 Core Decision Engine"]
        PII["PII Redactor<br/><i>13 Patterns</i>"]
        Injection["Prompt Injection Scanner<br/><i>3-Layer Defense</i>"]
        Retrieval["Hybrid Retrieval<br/><i>Sparse + Dense + RRF</i>"]
        Routing["ML Routing Engine<br/><i>30 Intent Categories</i>"]
        Confidence["Confidence Calculator<br/><i>5-Signal Fusion</i>"]
        Policy["Policy Gate<br/><i>OPA / Local Rules</i>"]
        Generation["Response Generator<br/><i>Template / Ollama LLM</i>"]
        Handoff["Handoff Service<br/><i>Escalation Queue</i>"]
    end

    subgraph ML["🤖 ML Services"]
        ModelServer["Model Server<br/><i>Port 9000</i>"]
        Shadow["Shadow Evaluator<br/><i>A/B Testing</i>"]
        Registry["Model Registry<br/><i>Lifecycle + Lineage</i>"]
    end

    subgraph Data["💾 Data Layer"]
        PG["PostgreSQL 16<br/>+ pgvector"]
        Redis["Redis 7<br/><i>Rate Limits + Cache</i>"]
        OPA["OPA Server<br/><i>Rego Policies</i>"]
    end

    subgraph Observe["📊 Observability"]
        Prom["Prometheus<br/><i>25+ Metrics</i>"]
        Grafana["Grafana<br/><i>Dashboards</i>"]
        Alert["Alertmanager<br/><i>14 Alert Rules</i>"]
        Jaeger["Jaeger<br/><i>Distributed Tracing</i>"]
    end

    subgraph Integrations["🔌 Integrations"]
        PubSub["Google Pub/Sub<br/><i>Event Bus</i>"]
        Temporal["Temporal<br/><i>Workflow Engine</i>"]
        MCP["MCP Server<br/><i>AI Tool Protocol</i>"]
        Vault["HashiCorp Vault<br/><i>Secrets</i>"]
    end

    Client --> LB --> NGINX --> Auth
    Auth --> RateLimit
    RateLimit --> PII --> Injection --> Retrieval
    Retrieval --> Routing --> Confidence --> Policy
    Policy --> Generation
    Policy --> Handoff
    Routing -.-> ModelServer
    Routing -.-> Shadow
    Shadow -.-> Registry
    Retrieval --> PG
    RateLimit --> Redis
    Policy -.-> OPA
    Auth --> Prom --> Grafana
    Prom --> Alert
    Auth --> Jaeger
    Handoff -.-> PubSub
    Handoff -.-> Temporal
    Auth -.-> Vault
    MCP --> Auth

    style External fill:#f0f4ff,stroke:#4a90d9
    style Ingress fill:#fff3e0,stroke:#fb8c00
    style API fill:#e8f5e9,stroke:#43a047
    style Core fill:#fce4ec,stroke:#e53935
    style ML fill:#f3e5f5,stroke:#8e24aa
    style Data fill:#e0f2f1,stroke:#00897b
    style Observe fill:#fff8e1,stroke:#f9a825
    style Integrations fill:#e8eaf6,stroke:#3949ab
```

### 3.2 Component Interaction Map

```mermaid
graph LR
    subgraph Request["Request Path"]
        A["POST /v1/assist/decide"] --> B["JWT Verification"]
        B --> C["Rate Limit Check"]
        C --> D["PII Redaction"]
        D --> E["Injection Scan"]
        E --> F["Idempotency Cache"]
    end

    subgraph Processing["Processing Engine"]
        F --> G["Evidence Retrieval"]
        G --> H["Route Prediction"]
        H --> I["Shadow Prediction"]
        I --> J["Confidence Score"]
        J --> K["Policy Evaluation"]
    end

    subgraph Output["Output Path"]
        K -->|Recommend| L["Response Generation"]
        K -->|Abstain / Escalate| M["Create Handoff"]
        L --> N["Anti-Copy Check"]
        N --> O["Output Validation"]
        M --> P["Event Publisher"]
        O --> P
        P --> Q["Persist to DB"]
        Q --> R["Return Response"]
    end

    style Request fill:#e3f2fd,stroke:#1565c0
    style Processing fill:#fff3e0,stroke:#ef6c00
    style Output fill:#e8f5e9,stroke:#2e7d32
```

### 3.3 Deployment Topology

```mermaid
graph TB
    subgraph Cloud["☁️ Production Deployment"]
        CLB["Cloud Load Balancer<br/><i>TLS 1.3 Termination</i>"]

        subgraph K8s["Kubernetes Cluster"]
            subgraph AppNS["Namespace: production"]
                NGINX["nginx-ingress"]
                API1["decision-api<br/>Pod 1"]
                API2["decision-api<br/>Pod 2"]
                APIN["decision-api<br/>Pod N"]
                HPA["HPA: 2–20 replicas<br/><i>CPU 70% · Memory 80%</i>"]
                PDB["PDB: minAvailable 2"]
                MS1["model-server<br/>Pod 1"]
                MS2["model-server<br/>Pod 2"]
            end

            subgraph DataNS["Namespace: data"]
                PG["PostgreSQL 16 + pgvector<br/><i>Regional HA · PITR</i>"]
                RD["Redis 7<br/><i>HA Pair · TLS + Auth</i>"]
            end

            subgraph MonNS["Namespace: monitoring"]
                PR["Prometheus<br/><i>15s scrape · 15d retention</i>"]
                GR["Grafana<br/><i>12 Dashboard Panels</i>"]
                AM["Alertmanager<br/><i>PagerDuty + Slack</i>"]
                JA["Jaeger<br/><i>OTLP Traces</i>"]
            end
        end
    end

    CLB --> NGINX
    NGINX --> API1 & API2 & APIN
    HPA -.->|autoscale| API1
    PDB -.->|protect| API1
    API1 & API2 & APIN --> PG & RD
    API1 & API2 & APIN --> MS1 & MS2
    API1 & API2 & APIN -.-> PR
    PR --> GR & AM
    API1 -.-> JA

    style Cloud fill:#f5f5f5,stroke:#424242
    style K8s fill:#e3f2fd,stroke:#1565c0
    style AppNS fill:#e8f5e9,stroke:#2e7d32
    style DataNS fill:#fff3e0,stroke:#ef6c00
    style MonNS fill:#fce4ec,stroke:#c62828
```

---

## 4. Request Lifecycle — The Full Pipeline

Every `POST /v1/assist/decide` request passes through **18 stages**. Here is what happens at each stage, why it happens, and how data is transformed.

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API Gateway
    participant AU as Auth Service
    participant RL as Rate Limiter
    participant PI as PII Redactor
    participant IS as Injection Scanner
    participant IC as Idempotency Cache
    participant RT as Retrieval Service
    participant RO as Routing Engine
    participant SH as Shadow Evaluator
    participant CF as Confidence Scorer
    participant PO as Policy Gate
    participant GN as Generator
    participant HO as Handoff Service
    participant DB as PostgreSQL
    participant EB as Event Bus

    C->>A: POST /v1/assist/decide
    A->>AU: 1· Verify JWT token
    AU-->>A: AuthContext (subject, tenant, permissions)
    A->>RL: 2· Check rate limit
    RL-->>A: Allowed / 429 Too Many Requests

    rect rgb(255, 248, 225)
        Note over PI,IS: Input Sanitization
        A->>PI: 3· Redact PII from issue_text
        PI-->>A: Sanitized text + redaction_count
        A->>IS: 4· Scan for prompt injection
        IS-->>A: risk_score (reject if > 0.60)
    end

    A->>IC: 5· Check idempotency cache
    IC-->>A: Cache hit → return cached response

    rect rgb(227, 242, 253)
        Note over RT,RO: Evidence & Classification
        A->>RT: 6· Hybrid search (sparse + dense + RRF)
        RT->>DB: FTS query + vector cosine search
        DB-->>RT: Ranked evidence chunks
        RT-->>A: Top-k EvidenceChunks (reranked, deduped)

        A->>RO: 7· Predict route + escalation
        RO-->>A: Probabilities + OOD + contradiction + intents
    end

    A->>SH: 8· Shadow/canary prediction (if enabled)
    SH-->>A: Challenger prediction (persisted, no user impact)

    rect rgb(232, 245, 233)
        Note over CF,PO: Decision Making
        A->>CF: 9· Compute multi-signal confidence
        CF-->>A: Confidence breakdown (5 components)
        A->>PO: 10· Evaluate policy
        PO-->>A: recommend / abstain / escalate
    end

    alt Decision = RECOMMEND
        rect rgb(243, 229, 245)
            A->>GN: 11· Generate grounded response
            GN-->>A: Draft response (anti-copy checked)
        end
    else Decision = ABSTAIN or ESCALATE
        A->>HO: 12· Create handoff payload
        HO-->>A: HandoffPayload (UUID + reasons + context)
    end

    rect rgb(255, 243, 224)
        Note over DB,EB: Persistence & Events
        A->>DB: 13· Write inference_requests + inference_results
        A->>DB: 14· Write handoff record (if escalated)
        A->>EB: 15· Publish decision event
    end

    A-->>C: DecideResponse
```

### Stage-by-Stage Breakdown

| # | Stage | What Happens | Why | Data Transformation |
|---|-------|-------------|-----|-------------------|
| 1 | **JWT Auth** | Verify token signature, issuer, audience, expiry. Extract subject, permissions, tenant_ids, roles | Multi-tenant isolation; RBAC authorization | Raw JWT → `AuthContext` object |
| 2 | **Rate Limiting** | Redis Lua script checks token bucket (120/tenant/min + 60/user/min) | Protect against abuse; fair resource sharing | Request → allow/deny decision |
| 3 | **PII Redaction** | 13 regex patterns mask SSN, CC, email, phone, IP, addresses, etc. | GDPR/HIPAA compliance; prevent PII reaching models | `"Call me at 555-0123"` → `"Call me at [REDACTED_PHONE]"` |
| 4 | **Injection Scan** | 18 regex rules + role marker count + entropy analysis → risk score | Prevent prompt manipulation attacks | Text → risk_score ∈ [0, 1]; reject if > 0.60 |
| 5 | **Idempotency** | SHA-256 of (request_id, tenant, section, text, risk, context) → cache lookup | Prevent duplicate processing; at-most-once semantics | Request → cache hit/miss |
| 6 | **Retrieval** | Sparse (FTS) + dense (pgvector cosine) → RRF fusion → rerank → dedup → staleness penalty | Ground responses in factual evidence | Query text → top-k `EvidenceChunk[]` with scores |
| 7 | **Routing** | Model predicts route probabilities + escalation. Compute OOD, contradiction, intents | Classify the issue and quantify uncertainty | Text + evidence → probability vector + metadata |
| 8 | **Shadow/Canary** | Challenger model runs in parallel (shadow) or serves a traffic bucket (canary) | Safe model evaluation without user impact | Same input → challenger prediction (persisted separately) |
| 9 | **Confidence** | 5-signal weighted formula combining route, evidence, escalation, OOD, contradiction | Calibrated decision boundary between act and defer | Multiple signals → single scalar ∈ [0, 1] |
| 10 | **Policy Gate** | OPA Rego rules or local fallback evaluate confidence + risk | Externalized, auditable decision policy | Confidence + risk → `DecisionType` enum |
| 11 | **Generation** | Template (structured Markdown) or Ollama LLM (channel-aware prompt + style examples) | Provide actionable response to the customer | Evidence + intent + channel → draft response text |
| 12 | **Anti-Copy** | Jaccard ≥ 0.82, 4-gram ≥ 0.55, evidence copy ≥ 0.90 → retry once | Ensure originality; prevent verbatim regurgitation | Draft → validated draft (or retry with modified prompt) |
| 13 | **Output Validation** | Length bounds (10–2000), PII re-check, forbidden content (ChatML, URLs) | Last line of defense for safety | Draft → pass/fail with violation reasons |
| 14 | **RAG Metrics** | Faithfulness, hallucination ratio, citation coverage, ROUGE-L | Monitor RAG quality over time | Response + evidence → quality scores |
| 15 | **Persistence** | Write to inference_requests, inference_results, handoffs tables | Auditability; model evaluation; compliance | Full payload → database rows |
| 16 | **Event Publish** | Emit decision_completed or handoff_created to event bus | Downstream integrations; async processing | Decision → Pub/Sub message |
| 17 | **Guardrails** | Force handoff if model used fallback or confidence outside [0.10, 0.99] | Safety net for edge cases | Decision → potentially overridden to escalate |
| 18 | **Return** | Assemble DecideResponse with all metadata | Complete response to the caller | Internal state → JSON response |

---

## 5. Data Architecture

### 5.1 Entity Relationship Diagram

```mermaid
erDiagram
    tenants ||--o{ doc_chunks : "owns"
    tenants ||--o{ inference_requests : "owns"
    tenants ||--o{ feedback_events : "owns"
    tenants ||--o{ handoffs : "owns"

    tenants {
        uuid tenant_id PK
        text name
        timestamptz created_at
    }

    doc_chunks {
        uuid chunk_id PK
        uuid tenant_id FK
        text source
        text section
        text body
        tsvector body_tsv "GIN Index for FTS"
        vector_384 embedding "HNSW Index m=16 ef=64"
        timestamptz created_at
    }

    inference_requests {
        uuid request_id PK
        uuid tenant_id FK
        text issue_text
        text section
        text risk_level
        jsonb context
        text idempotency_hash "UNIQUE"
        timestamptz created_at
    }

    inference_results {
        uuid result_id PK
        uuid request_id FK
        text decision_type
        float confidence
        jsonb route_probabilities
        float escalation_prob
        text draft_response
        text model_variant
        jsonb evidence_chunks
        jsonb confidence_breakdown
        jsonb rag_quality_metrics
        float cost_estimate
        timestamptz created_at
    }

    handoffs {
        uuid handoff_id PK
        uuid request_id FK
        uuid tenant_id FK
        text status "open/in_review/resolved/closed"
        text_arr reason_codes
        text summary_text
        jsonb evidence
        jsonb route_probabilities
        text reviewer_id
        text final_decision
        text final_resolution_path
        timestamptz created_at
        timestamptz updated_at
    }

    feedback_events {
        uuid feedback_id PK
        uuid request_id FK
        uuid tenant_id FK
        int rating
        text comment
        text feedback_source "user or reviewer"
        timestamptz created_at
    }

    reviewer_outcomes {
        uuid outcome_id PK
        uuid handoff_id FK
        text reviewer_id
        text final_decision
        text final_resolution_path
        timestamptz reviewed_at
    }

    model_shadow_predictions {
        uuid prediction_id PK
        uuid request_id FK
        text model_variant
        jsonb route_probabilities
        float escalation_prob
        float confidence
        timestamptz created_at
    }

    model_rollout_config {
        uuid config_id PK
        int canary_percent
        float accuracy_gate
        float recall_gate
        float ece_gate
        float abstain_gate
        int min_sample_gate
        boolean active
        timestamptz created_at
    }

    inference_requests ||--o| inference_results : "has result"
    inference_requests ||--o{ handoffs : "may escalate"
    inference_requests ||--o{ feedback_events : "receives feedback"
    inference_requests ||--o{ model_shadow_predictions : "has shadow prediction"
    handoffs ||--o| reviewer_outcomes : "closed by reviewer"
```

### 5.2 Storage Backend Strategy

**Why different backends?** The platform must run in two modes: (1) zero-dependency development on a laptop, and (2) production with full durability and scale. Every store has a production and a dev variant.

| Store Class | Production Backend | Dev Fallback | What It Stores | Why Two Variants? |
|------------|-------------------|--------------|----------------|-------------------|
| `PostgresRetrievalStore` | PostgreSQL + pgvector | `InMemoryRetrievalStore` (JSON file) | Evidence chunks with embeddings | Dev doesn't need a database for basic testing |
| `PostgresInferenceStore` | PostgreSQL | `NoopInferenceStore` | Inference requests, results, handoffs | Dev can skip persistence for rapid iteration |
| `PostgresFeedbackStore` | PostgreSQL | `NoopFeedbackStore` | User ratings and comments | Same — noop in dev |
| `PostgresHandoffStore` | PostgreSQL | `NoopHandoffStore` | Escalation queue with status tracking | Same — noop in dev |
| `PostgresModelOpsStore` | PostgreSQL | `NoopModelOpsStore` | Shadow predictions, rollout config | Same — noop in dev |
| `RedisRateLimiter` | Redis 7 | `NoopRateLimiter` | Token-bucket counters | Dev doesn't need rate limiting |
| `VaultSecretsProvider` | HashiCorp Vault | `EnvVarSecretsProvider` | Encrypted secrets with rotation | Dev uses plain env vars |

### 5.3 Row-Level Security (Multi-Tenancy)

**What:** When `RLS_ENABLED=true`, PostgreSQL automatically filters every query by `tenant_id`.

**Why:** Defense-in-depth tenant isolation — even if the application has a bug, one tenant's data can never leak to another.

**How:** Each connection sets `SET LOCAL app.current_tenant = '<id>'`. RLS policies enforce `tenant_id = current_setting('app.current_tenant')`.

**When:** Always in production. Application-level WHERE clauses provide a second layer.

```mermaid
sequenceDiagram
    participant App as Application
    participant PG as PostgreSQL

    App->>PG: SET LOCAL app.current_tenant = 'tenant-abc'
    App->>PG: SELECT * FROM inference_requests WHERE ...
    Note over PG: RLS Policy automatically adds:<br/>WHERE tenant_id = current_setting('app.current_tenant')
    PG-->>App: Only tenant-abc rows returned
```

### 5.4 Data Retention

| Table | Default Retention | Why |
|-------|-------------------|-----|
| `inference_requests` + `inference_results` | 180 days | Balance audit needs vs. storage cost |
| `feedback_events` | 365 days | Longer retention for model evaluation |
| `handoffs` | 180 days | Same as inference |
| `doc_chunks` | No expiry | Evidence must persist |

Automated cleanup via `DATA_RETENTION_INFERENCE_DAYS` and `DATA_RETENTION_FEEDBACK_DAYS` settings.

---

## 6. Data Transformation Pipeline

### 6.1 Complete Data Flow

```mermaid
flowchart TB
    subgraph Input["📥 INPUT"]
        Raw["Raw Customer Issue<br/><code>My order #12345 hasn't arrived.<br/>Call me at 555-0123.</code>"]
    end

    subgraph Sanitize["🛡️ SANITIZATION"]
        PII["PII Redactor ➜ 13 regex patterns"]
        Sanitized["<code>My order [REDACTED_ORDER] hasn't<br/>arrived. Call me at [REDACTED_PHONE].</code>"]
        Inject["Injection Scanner ➜ risk_score = 0.02 ✅"]
    end

    subgraph Embed["🔢 EMBEDDING"]
        Embed1["Sentence Transformer<br/>all-MiniLM-L6-v2"]
        Vec["384-dim Vector<br/><code>[0.023, -0.118, 0.445, ...]</code>"]
    end

    subgraph Search["🔍 RETRIEVAL"]
        Sparse["Sparse: ts_rank_cd + plainto_tsquery"]
        Dense["Dense: pgvector cosine (HNSW)"]
        RRF["RRF Fusion: score = Σ 1/(k + rank)"]
        Rerank["Cross-Encoder: 0.30·token + 0.25·bigram<br/>+ 0.15·trigram + 0.30·original"]
        Dedup["Dedup: token-set overlap ≥ 0.85 ➜ drop"]
        Stale["Staleness: -0.0005/day after 180d"]
        Evidence["Top-k Evidence Chunks with scores"]
    end

    subgraph Route["🧭 ROUTING"]
        Model["ML Engine ➜ route probabilities"]
        Probs["{shipping_delay: 0.72,<br/>order_status: 0.18, ...}"]
        OOD["OOD Score: 0.12"]
        Contra["Contradiction Score: 0.00"]
        Intent["Intent: shipping_delay"]
    end

    subgraph Score["📊 CONFIDENCE"]
        Conf["conf = 0.45·0.72 + 0.25·0.85<br/>+ 0.20·0.88 - 0.07·0.12 - 0.03·0.00"]
        ConfVal["= 0.73"]
    end

    subgraph Decide["⚖️ POLICY"]
        PolicyEval["0.73 > threshold 0.55 ➜ RECOMMEND"]
    end

    subgraph Generate["✍️ GENERATION"]
        Gen["Ollama LLM or Template"]
        AntiCopy["Anti-Copy: Jaccard 0.31 ✅<br/>4-gram 0.18 ✅ · Evidence 0.42 ✅"]
        Output["Output Validation: Length ✅ PII ✅"]
        Draft["Final: <i>I understand your concern<br/>about the delayed order...</i>"]
    end

    subgraph Persist["💾 PERSISTENCE"]
        DB["PostgreSQL ➜ inference_requests<br/>+ inference_results"]
        Events["Event Bus ➜ decision_completed"]
    end

    Raw --> PII --> Sanitized --> Inject
    Inject --> Embed1 --> Vec
    Vec --> Sparse & Dense
    Sparse --> RRF
    Dense --> RRF
    RRF --> Rerank --> Dedup --> Stale --> Evidence
    Evidence --> Model
    Model --> Probs & OOD & Contra & Intent
    Probs --> Conf
    OOD --> Conf
    Contra --> Conf
    Conf --> ConfVal --> PolicyEval
    PolicyEval --> Gen --> AntiCopy --> Output --> Draft
    Draft --> DB & Events

    style Input fill:#e3f2fd,stroke:#1565c0
    style Sanitize fill:#fff3e0,stroke:#ef6c00
    style Embed fill:#f3e5f5,stroke:#8e24aa
    style Search fill:#e0f2f1,stroke:#00897b
    style Route fill:#fce4ec,stroke:#c62828
    style Score fill:#fff8e1,stroke:#f9a825
    style Decide fill:#e8eaf6,stroke:#3949ab
    style Generate fill:#e8f5e9,stroke:#2e7d32
    style Persist fill:#efebe9,stroke:#795548
```

### 6.2 Every Transformation — What, Why, How, When

#### 🔴 PII Redaction

| Aspect | Detail |
|--------|--------|
| **What** | 13 regex patterns detect and mask sensitive personal information |
| **Why** | GDPR/HIPAA compliance. Prevent PII from reaching ML models, LLM prompts, or being stored in logs |
| **How** | Sequential regex replacement: SSN → `[REDACTED_SSN]`, credit cards (Luhn-valid prefixes) → `[REDACTED_CC]`, emails → `[REDACTED_EMAIL]`, phones → `[REDACTED_PHONE]`, IPs → `[REDACTED_IP]`, etc. |
| **When** | **First** transformation — before anything else touches the text |
| **Patterns** | SSN · Credit Card · Email · Phone · IP · Order Number · Invoice · Account ID · Street Address · Client Name · Monetary Amount · Date · URL |

#### 🟠 Prompt Injection Defense

| Aspect | Detail |
|--------|--------|
| **What** | 3-layer scoring system produces a risk score ∈ [0, 1] |
| **Why** | Adversarial inputs can manipulate LLM behavior, extract system prompts, or inject harmful instructions |
| **How** | **Layer 1:** 18 regex rules (instruction override, role switching, prompt extraction, delimiter injection, jailbreak phrases). **Layer 2:** Count role markers (system:/user:/assistant:). **Layer 3:** Statistical analysis (instruction density, suspicious token clusters, character entropy) |
| **When** | After PII redaction, before any model inference |
| **Formula** | `risk = min(1.0, rules × 0.25 + density × 0.4 + markers × 0.1 + suspicious × 0.05)` |

#### 🟡 Embedding

| Aspect | Detail |
|--------|--------|
| **What** | Transform text into a fixed-dimensional numerical vector for semantic search |
| **Why** | Enable meaning-based retrieval that goes beyond keyword matching ("order delayed" ≈ "shipment late") |
| **How** | Three backends: `LocalHash` → 64-dim SHA-256 hash (dev). `SentenceTransformer` → 384-dim `all-MiniLM-L6-v2` (production). `Api` → 1536-dim OpenAI (external) |
| **When** | At query time for search; at ingestion time for document indexing (`make reindex-embeddings`) |

#### 🟢 Hybrid Retrieval

| Aspect | Detail |
|--------|--------|
| **What** | Combine sparse (lexical) and dense (semantic) search with multi-stage ranking |
| **Why** | Sparse catches exact terms ("invoice #INV-2024"). Dense captures semantics ("payment problem" ≈ "billing issue"). Together they cover more scenarios than either alone |
| **How** | **Sparse:** `ts_rank_cd` with `plainto_tsquery` over GIN-indexed `body_tsv`. **Dense:** pgvector cosine `1 - (embedding <=> q)` via HNSW. **Fusion:** RRF `score = Σ 1/(60 + rank)`. **Rerank:** `0.30·token + 0.25·bigram + 0.15·trigram + 0.30·original`. **Dedup:** overlap ≥ 0.85 → drop. **Staleness:** `-0.0005 × days_over_180` (max 0.15) |
| **When** | Every decide request, after sanitization |

#### 🔵 Route Classification

| Aspect | Detail |
|--------|--------|
| **What** | Predict which resolution path the issue should take, with calibrated probabilities |
| **Why** | Different issues require different handling — billing disputes vs. shipping delays vs. technical bugs |
| **How** | **Heuristic:** 30+ keyword sets from taxonomy → softmax. **Artifact:** JSON weights + temperature-calibrated softmax + Platt sigmoid. **HTTP:** External model server. All wrapped in `FallbackRoutingModelEngine` (primary → fallback chain) |
| **When** | After evidence retrieval (evidence context informs routing) |

#### 🟣 Confidence Calculation

| Aspect | Detail |
|--------|--------|
| **What** | Fuse 5 independent signals into a single calibrated confidence scalar |
| **Why** | Single-model probability is unreliable. Each signal captures a different uncertainty dimension |
| **How** | `conf = 0.45·route_conf + 0.25·evidence_score + 0.20·(1 - escalation) - 0.07·ood - 0.03·contradiction` |
| **When** | After routing, before policy evaluation |
| **Signals** | **route_conf:** Top route probability. **evidence_score:** Average retrieval relevance. **escalation_safety:** 1 minus escalation probability. **ood_penalty:** Out-of-distribution score. **contradiction_penalty:** Evidence-issue contradiction score |

#### ⚪ Response Generation

| Aspect | Detail |
|--------|--------|
| **What** | Generate a customer-facing response grounded in retrieved evidence |
| **Why** | Reduce agent workload by drafting accurate, citation-backed responses |
| **How** | **Template:** Structured Markdown with evidence citations — zero LLM dependency. **Ollama:** Rich prompt with evidence, history, profile, channel constraints (Twitter 280 / chat 600 / email 1500 / phone 800 chars), style examples from JSONL |
| **When** | Only when policy decision is RECOMMEND |
| **Anti-Copy** | Token-set Jaccard ≥ 0.82 → fail. 4-gram overlap ≥ 0.55 → fail. Per-evidence copy ≥ 0.90 → fail. On failure: retry once with modified prompt |

---

## 7. ML / AI Pipeline

### 7.1 Model Architecture

```mermaid
graph TB
    subgraph Engines["🤖 Routing Model Engines"]
        H["<b>Heuristic</b><br/>Keyword scoring<br/>30+ intent keyword sets<br/>Softmax normalization"]
        A["<b>Artifact</b><br/>JSON model weights<br/>Temperature-calibrated softmax<br/>Platt-calibrated sigmoid"]
        HTTP["<b>HTTP</b><br/>External model server<br/>Port 9000<br/>httpx POST"]
    end

    subgraph Fallback["🔄 Fallback Chain"]
        FB["FallbackRoutingModelEngine<br/><i>Primary → Fallback</i><br/>Tracks last_used_fallback flag"]
    end

    subgraph Shadow["👥 Shadow / Canary"]
        SE["Shadow Evaluator<br/><i>Challenger runs in parallel</i><br/>Zero user impact"]
        CE["Canary Bucketing<br/><i>SHA-256(tenant:request) % 100</i><br/>Deterministic split"]
    end

    subgraph Quality["✅ Quality Gates"]
        QG["Route accuracy ≥ 0.75<br/>Escalation recall ≥ 0.70<br/>Calibration ECE ≤ 0.15<br/>Abstain rate ≤ 0.35<br/>Min samples ≥ 200"]
    end

    H & A & HTTP --> FB
    FB --> SE & CE
    SE --> QG
    CE --> QG

    style Engines fill:#f3e5f5,stroke:#8e24aa
    style Fallback fill:#fff3e0,stroke:#ef6c00
    style Shadow fill:#e3f2fd,stroke:#1565c0
    style Quality fill:#e8f5e9,stroke:#2e7d32
```

### 7.2 Model Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Development: Register artifact

    Development --> Shadow: Enable shadow mode
    Shadow --> Canary: Quality gates pass
    Canary --> Production: 100% traffic, all gates pass
    Production --> Archived: Replaced by new model
    Production --> Rollback: Quality degradation

    Rollback --> Production: Emergency revert

    state Shadow {
        [*] --> RunParallel: Every request
        RunParallel --> PersistPrediction: Write to model_shadow_predictions
        PersistPrediction --> EvaluateGates: Batch evaluate
    }

    state Canary {
        [*] --> Bucket10: 10% traffic
        Bucket10 --> Bucket25: Monitor 5min → pass
        Bucket25 --> Bucket50: Monitor 5min → pass
        Bucket50 --> Bucket100: Monitor 10min → pass
    }
```

**Quality Gates — What, Why, When:**

| Gate | Threshold | What It Measures | Why It Matters | When Checked |
|------|-----------|-----------------|----------------|--------------|
| Route Accuracy | ≥ 0.75 | Fraction of correct classifications | Core model performance | Shadow + canary evaluation |
| Escalation Recall | ≥ 0.70 | Fraction of true escalations caught | Missing an escalation = customer harm | Shadow + canary evaluation |
| Calibration ECE | ≤ 0.15 | Expected calibration error | Uncalibrated confidence → bad decisions | Shadow + canary evaluation |
| Abstain Rate | ≤ 0.35 | Fraction routing to human | Too many abstains = no automation value | Shadow + canary evaluation |
| Min Samples | ≥ 200 | Evaluation sample count | Small samples = unreliable metrics | Before any gate evaluation |

### 7.3 Embedding Pipeline

| Backend | Dimensions | Model | Use Case | Latency |
|---------|-----------|-------|----------|---------|
| `LocalHashEmbeddingProvider` | 64 | SHA-256 hash | Development only | < 1ms |
| `SentenceTransformerEmbeddingProvider` | 384 | `all-MiniLM-L6-v2` (80MB) | Production default | ~10ms |
| `ApiEmbeddingProvider` | 1536 | OpenAI `text-embedding-3-small` | Highest quality (external) | ~100ms |

**Index:** pgvector HNSW with `m=16, ef_construction=64` for approximate nearest neighbor search.

### 7.4 RAG Quality Metrics

Every generated response is evaluated:

| Metric | What It Measures | Formula | Target |
|--------|-----------------|---------|--------|
| **Faithfulness** | Grounding in evidence | Bigram/trigram overlap with evidence | > 0.60 |
| **Hallucination Ratio** | Fabricated content | `1 - faithfulness` | < 0.30 |
| **Citation Coverage** | Evidence referenced | Cited chunks / total chunks | > 0.50 |
| **ROUGE-L F1** | Textual overlap | Longest common subsequence | Informational |
| **Recall@k** | Retrieval completeness | Relevant in top-k / total relevant | > 0.70 |
| **MRR** | Ranking quality | `1 / rank_of_first_relevant` | > 0.50 |

### 7.5 Confidence Formula

The multi-signal confidence score:

$$\text{confidence} = \underbrace{0.45 \cdot p_{\text{top}}}_{\text{route confidence}} + \underbrace{0.25 \cdot \bar{s}_{\text{evidence}}}_{\text{evidence quality}} + \underbrace{0.20 \cdot (1 - p_{\text{esc}})}_{\text{escalation safety}} - \underbrace{0.07 \cdot \text{OOD}}_{\text{novelty penalty}} - \underbrace{0.03 \cdot \text{contradiction}}_{\text{conflict penalty}}$$

The OOD (Out-of-Distribution) score:

$$\text{OOD} = 0.45 \cdot (1 - p_{\text{top}}) + 0.30 \cdot (1 - s_{\text{top\_evidence}}) + 0.10 \cdot r_{\text{unknown}} + \text{brevity} + 0.05 \cdot \text{diversity}$$

---

## 8. Security Architecture

### 8.1 Defense-in-Depth Layers

```mermaid
graph TB
    subgraph L1["Layer 1 · Network"]
        TLS["TLS 1.3 Termination"]
        NP["K8s Network Policy<br/><i>nginx + monitoring ingress only</i>"]
    end

    subgraph L2["Layer 2 · Authentication"]
        JWT["JWT Verification<br/><i>Issuer · Audience · Expiry</i>"]
        RBAC["Role-Based Access Control<br/><i>platform_admin = wildcard</i>"]
        Tenant["Tenant Isolation<br/><i>tenant_ids claim</i>"]
    end

    subgraph L3["Layer 3 · Rate Limiting"]
        RL["Redis Token Bucket<br/><i>Atomic Lua Script</i>"]
        TRL["Per-Tenant: 120 req/min"]
        URL["Per-User: 60 req/min"]
    end

    subgraph L4["Layer 4 · Input Sanitization"]
        PIILayer["PII Redaction<br/><i>13 patterns</i>"]
        InjLayer["Prompt Injection<br/><i>3-layer defense</i>"]
    end

    subgraph L5["Layer 5 · Output Validation"]
        LenCheck["Length Bounds: 10–2000 chars"]
        PIIRecheck["PII Re-scan on output"]
        Forbidden["Forbidden: ChatML · URLs · Markdown injection"]
    end

    subgraph L6["Layer 6 · Data Protection"]
        RLS["Row-Level Security<br/><i>Tenant isolation at DB</i>"]
        VaultL["Vault / KMS<br/><i>Secret rotation</i>"]
        Retention["Data Retention<br/><i>Automated cleanup</i>"]
    end

    subgraph L7["Layer 7 · Container Hardening"]
        NonRoot["runAsNonRoot: true"]
        ReadOnly["readOnlyRootFilesystem"]
        NoCaps["drop: ALL capabilities"]
    end

    L1 --> L2 --> L3 --> L4 --> L5
    L6 -.-> L2
    L7 -.-> L1

    style L1 fill:#e8eaf6,stroke:#3949ab
    style L2 fill:#e3f2fd,stroke:#1565c0
    style L3 fill:#e0f2f1,stroke:#00897b
    style L4 fill:#fff3e0,stroke:#ef6c00
    style L5 fill:#fce4ec,stroke:#c62828
    style L6 fill:#f3e5f5,stroke:#8e24aa
    style L7 fill:#efebe9,stroke:#795548
```

### 8.2 Prompt Injection Defense Detail

```mermaid
graph LR
    Input["User Input"] --> L1["Layer 1<br/><b>18 Regex Rules</b>"]
    L1 --> L2["Layer 2<br/><b>Role Marker Count</b>"]
    L2 --> L3["Layer 3<br/><b>Statistical Analysis</b>"]
    L3 --> Score["Risk Score"]
    Score -->|"> 0.60"| Reject["REJECT ❌"]
    Score -->|"≤ 0.60"| Accept["ACCEPT ✅"]

    style Reject fill:#ffcdd2,stroke:#c62828
    style Accept fill:#c8e6c9,stroke:#2e7d32
```

**Layer 1 — Pattern matching (18 rules):**
- Instruction override: `"ignore previous instructions"`
- Role switching: `"you are now a..."`
- Prompt extraction: `"show me your prompt"`
- Delimiter injection: `"---system---"`
- Jailbreak phrases: `"DAN mode enabled"`

**Layer 2 — Role markers:**
- Count occurrences of `system:`, `user:`, `assistant:` — legitimate user input rarely contains these

**Layer 3 — Statistical signals:**
- Instruction density (imperative verbs per sentence)
- Suspicious token clusters
- Character entropy (abnormally high = possible obfuscation)

**Formula:** `risk = min(1.0, rules × 0.25 + density × 0.4 + markers × 0.1 + suspicious × 0.05)`

### 8.3 Production Config Guards

When `APP_ENV=production`, the application **refuses to start** if any of these guards fail:

| Guard | Rule | What It Prevents |
|-------|------|-----------------|
| `AUTH_ENABLED` | Must be `true` | Deploying with no authentication |
| `USE_POSTGRES` | Must be `true` | Running on in-memory stores in production |
| `RATE_LIMIT_ENABLED` | Must be `true` | No abuse protection |
| `PII_REDACTION_ENABLED` | Must be `true` | PII reaching models/logs |
| `METRICS_ENABLED` | Must be `true` | Running blind with no metrics |
| `POSTGRES_DSN` | No weak passwords (`postgres`, `password`, `changeme`, `test`, empty) | Default credentials in production |
| `EMBEDDING_BACKEND` | Must not be `local` | Hash embeddings in production |
| `JWT_SECRET_KEY` | Must not be a development default | Known secrets in production |

---

## 9. Observability Stack

### 9.1 Metrics (25+)

```mermaid
graph TB
    subgraph Metrics["Application Instruments 25+ Prometheus Metrics"]
        subgraph HTTP["HTTP"]
            M1["requests_total"]
            M2["duration_seconds ·histogram·"]
            M3["errors_total"]
        end
        subgraph Pipeline["Pipeline"]
            M4["decisions_total"]
            M5["handoffs_total"]
            M6["cache_hits"]
            M7["pipeline_stage_duration"]
            M8["inflight_requests ·gauge·"]
            M9["request_cost_dollars"]
        end
        subgraph MLMetrics["Model"]
            M10["routing_accuracy"]
            M11["calibration_ece"]
            M12["abstain_rate"]
            M13["shadow_predictions"]
        end
        subgraph RAGMetrics["RAG"]
            M14["faithfulness"]
            M15["hallucination_ratio"]
            M16["citation_coverage"]
        end
        subgraph SecMetrics["Security"]
            M17["injection_detections"]
            M18["rate_limit_exceeded"]
            M19["circuit_breaker_state"]
        end
    end

    style HTTP fill:#e3f2fd,stroke:#1565c0
    style Pipeline fill:#e8f5e9,stroke:#2e7d32
    style MLMetrics fill:#f3e5f5,stroke:#8e24aa
    style RAGMetrics fill:#fff3e0,stroke:#ef6c00
    style SecMetrics fill:#fce4ec,stroke:#c62828
```

### 9.2 Alert Rules (14)

| Alert | Severity | Owner | Condition |
|-------|----------|-------|-----------|
| `DecisionApiHighErrorRate` | 🔴 critical | `platform_oncall` | Error rate > 5% for 5m |
| `DecisionApiHighLatencyP95` | 🟡 warning | `platform_oncall` | p95 > 500ms for 5m |
| `DecisionApiHighLatencyP99` | 🔴 critical | `platform_oncall` | p99 > 1.2s for 5m |
| `DecisionApiLowThroughput` | 🟡 warning | `platform_oncall` | < 1 RPS for 10m |
| `ModelServingHighErrorRate` | 🟡 warning | `model_oncall` | Model server errors > 5% |
| `InputDriftDetected` | 🟡 warning | `model_oncall` | Input distribution shift |
| `ConfidenceDriftDetected` | 🟡 warning | `model_oncall` | Confidence distribution shift |
| `OutcomeDriftDetected` | 🟡 warning | `model_oncall` | Outcome distribution shift |
| `GuardrailFallbackSpike` | 🔴 critical | `model_oncall` | > 20% fallback rate |
| `HighHallucinationRate` | 🔴 critical | `model_oncall` | Hallucination > 30% |
| `LowFaithfulness` | 🟡 warning | `model_oncall` | Faithfulness < 60% |
| `HighAbstainRate` | 🟡 warning | `model_oncall` | Abstain rate > 50% |
| `HighInjectionRate` | 🔴 critical | `platform_oncall` | > 10% injection detections |
| `CircuitBreakerOpen` | 🔴 critical | `platform_oncall` | Circuit breaker tripped |

**Alert routing:** 🔴 Critical → **PagerDuty**. Model team 🟡 → **Slack** `#model-alerts`. Default → **Webhook**.

### 9.3 SLO Baselines

| Metric | Target |
|--------|--------|
| p50 Latency | ≤ 120ms |
| p95 Latency | ≤ 500ms |
| p99 Latency | ≤ 1.2s |
| Throughput (template) | ≥ 200 RPS |
| Throughput (Ollama) | ≥ 8 RPS |
| Cost/request (template) | ~$0.00005 |
| Cost/request (Ollama) | ~$0.00015 |

### 9.4 Circuit Breaker

**What:** Protects downstream services (model server, Ollama, external APIs) from cascading failures.

**States:** `CLOSED → OPEN → HALF_OPEN → CLOSED` (recovery) or back to `OPEN` (still failing).

**Config:** `failure_threshold=5`, `recovery_timeout=30s`, `half_open_max_calls=1`, `success_threshold=2`.

---

## 10. Infrastructure & Deployment

### 10.1 Docker Compose (8 Services, 4 Profiles)

```mermaid
graph TB
    subgraph Default["Default · Always On"]
        PG["🐘 PostgreSQL 16 + pgvector<br/>Port 5432"]
        RD["🔴 Redis 7 Alpine<br/>Port 6379"]
    end

    subgraph PolicyP["Policy Profile"]
        OPA["📜 OPA 0.69.0<br/>Port 8181"]
    end

    subgraph ModelP["Model Serving Profile"]
        MS["🤖 Model Server<br/>Port 9000"]
    end

    subgraph ObsP["Observability Profile"]
        PR["📊 Prometheus v2.55.1<br/>Port 9090"]
        AM["🔔 Alertmanager v0.28.0<br/>Port 9093"]
        GR["📈 Grafana v11.2.2<br/>Port 3000"]
        JG["🔍 Jaeger v1.60<br/>Port 16686"]
        PR --> AM
        PR --> GR
    end

    style Default fill:#e8f5e9,stroke:#2e7d32
    style PolicyP fill:#e3f2fd,stroke:#1565c0
    style ModelP fill:#f3e5f5,stroke:#8e24aa
    style ObsP fill:#fff3e0,stroke:#ef6c00
```

```bash
# Start core infrastructure
docker compose up -d

# Add observability
docker compose --profile observability up -d

# Add model server
docker compose --profile model-serving up -d

# Add OPA policy engine
docker compose --profile policy up -d

# Start everything
docker compose --profile observability --profile model-serving --profile policy up -d
```

### 10.2 CI/CD Pipeline (5 Stages)

```mermaid
graph LR
    subgraph S1["Stage 1<br/>🔍 Lint & Test"]
        Lint["Static Analysis"]
        Test["pytest + PG + Redis"]
    end

    subgraph S2["Stage 2<br/>🛡️ Security"]
        Audit["pip-audit"]
        Trivy["Trivy Container"]
        TH["TruffleHog Secrets"]
    end

    subgraph S3["Stage 3<br/>📦 Build"]
        B1["decision-api image"]
        B2["model-server image"]
    end

    subgraph S4["Stage 4<br/>🟡 Staging"]
        SD["Deploy + Smoke Test"]
        QG["Quality Gate"]
    end

    subgraph S5["Stage 5<br/>🟢 Production"]
        C10["Canary 10%"]
        Mon["Monitor 5min"]
        Full["Promote 100%"]
    end

    S1 --> S2 --> S3 --> S4 --> S5

    style S1 fill:#e3f2fd,stroke:#1565c0
    style S2 fill:#fce4ec,stroke:#c62828
    style S3 fill:#f3e5f5,stroke:#8e24aa
    style S4 fill:#fff3e0,stroke:#ef6c00
    style S5 fill:#e8f5e9,stroke:#2e7d32
```

| Stage | What | How | Why |
|-------|------|-----|-----|
| **1. Lint & Test** | Static analysis + full test suite | pytest with Postgres + Redis service containers | Catch bugs and regressions early |
| **2. Security** | Dependency CVEs + container scan + secret leaks | pip-audit, Trivy, TruffleHog | Prevent shipping vulnerable code |
| **3. Build** | Docker images for API + model server | Buildx with layer caching | Reproducible, immutable artifacts |
| **4. Staging** | Container smoke test or Helm deploy | Health + readiness + preflight + quality gate | Validate in a prod-like environment |
| **5. Production** | Canary 10% → monitor → promote 100% | Helm upgrade with canary flag + Prometheus validation | Gradual rollout with automated rollback |

**Dual modes:**
- `DEPLOY_TARGET=local` → Container smoke test (no cloud required)
- `DEPLOY_TARGET=cloud` → Push to registry, Helm deploy to remote K8s

**Rollback triggers:** Error rate > 5%, p95 > 1000ms, or any deployment failure.

### 10.3 Kubernetes Resources

| Resource | Configuration |
|----------|--------------|
| **HPA** | 2–20 replicas; CPU target 70%; memory target 80% |
| **PDB** | minAvailable: 1 (staging), 2 (production) |
| **Topology** | Pod anti-affinity; maxSkew: 1; zone spread |
| **Network Policy** | Ingress from `nginx-ingress` + `monitoring` only |
| **Security Context** | `runAsNonRoot`, `readOnlyRootFilesystem`, `drop: ALL` |
| **Resources** | Requests: 250m–500m CPU, 256Mi–512Mi mem. Limits: 1–2 CPU, 512Mi–2Gi mem |
| **TLS** | cert-manager + Let's Encrypt; TLS 1.3 |

### 10.4 Database Migrations

10 sequential migrations in `migrations/`:

| # | File | Creates |
|---|------|---------|
| 1 | `0001_init_core_tables.sql` | `tenants`, `doc_chunks` (pgvector embedding HNSW, GIN body_tsv) |
| 2 | `0002_inference_audit_tables.sql` | `inference_requests`, `inference_results`, `handoffs` |
| 3 | `0003_feedback_events.sql` | `feedback_events` |
| 4 | `0004_model_ops_evaluation.sql` | `reviewer_outcomes`, `model_shadow_predictions`, `model_rollout_config` |
| 5 | `0005_rollout_evidence.sql` | Rollout evidence tracking |
| 6 | `0006_rollout_gate_min_sample_size.sql` | Gate min sample size column |
| 7 | `0007_business_scorecard.sql` | Business scorecard tables |
| 8 | `0008_operational_controls.sql` | Operational control records |
| 9 | `0009_intent_taxonomy_pii_audit.sql` | Intent taxonomy + PII audit tables |
| 10 | `0010_tenant_rls_data_retention.sql` | Row-level security + data retention policies |

---

## 11. API Reference

### 11.1 Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Liveness probe — returns `{"status": "ok"}` |
| `GET` | `/ready` | None | Readiness probe — checks Postgres, Redis, model-serving |
| `GET` | `/metrics` | None | Prometheus metrics |
| `POST` | `/v1/assist/decide` | `assist:decide` | **Main decision pipeline** |
| `POST` | `/v1/assist/feedback` | `assist:feedback` | Record human feedback |
| `POST` | `/v1/assist/reindex` | `assist:reindex` | Trigger embedding reindex |
| `GET` | `/v1/assist/handoffs` | `assist:handoff:read` | List handoff queue (paginated) |
| `PATCH` | `/v1/assist/handoffs/{id}/status` | `assist:handoff:update` | Update handoff + capture ground truth |
| `POST` | `/v1/admin/reload-chunks` | `admin:reload` | Hot-reload knowledge chunks |

### 11.2 Example: Decision Request

```json
{
  "tenant_id": "acme-corp",
  "issue_text": "My order hasn't arrived and it's been 2 weeks",
  "section": "shipping",
  "context": {
    "customer_tier": "premium",
    "channel": "email",
    "conversation_history": ["I ordered on Jan 15th"]
  },
  "risk_level": "medium",
  "max_evidence_chunks": 5
}
```

### 11.3 Example: Decision Response

```json
{
  "decision": "recommend",
  "resolution_path_probs": [
    {"label": "shipping_delay", "probability": 0.72},
    {"label": "order_status", "probability": 0.18}
  ],
  "escalation_prob": 0.12,
  "confidence_breakdown": {
    "final": 0.73,
    "route_confidence": 0.72,
    "evidence_score": 0.85,
    "escalation_safety": 0.88,
    "ood_penalty": 0.08,
    "contradiction_penalty": 0.00
  },
  "evidence_pack": [
    {
      "chunk_id": "abc-123",
      "source": "shipping_policy.md",
      "section": "delays",
      "body": "Orders typically arrive within 5-7 business days...",
      "score": 0.91
    }
  ],
  "draft_response": "I understand your concern about the delayed order...",
  "policy_result": {
    "decision": "recommend",
    "source": "opa",
    "reason": "Confidence 0.73 exceeds threshold 0.55"
  },
  "handoff_payload": null,
  "trace_id": "abc123def456",
  "model_variant": "champion",
  "detected_intent": "shipping_delay",
  "pii_redacted": true
}
```

### 11.4 Intent Taxonomy (30 Categories)

| Category | Intents | Risk |
|----------|---------|------|
| **ACCOUNT** | `account_access`, `account_update`, `account_deletion` | Low–Medium |
| **ORDER** | `order_status`, `order_modification`, `order_cancellation` | Low–Medium |
| **PAYMENT** | `payment_issue`, `payment_method`, `payment_dispute` | Medium–High |
| **REFUND** | `refund_request`, `refund_status`, `refund_dispute` | Medium–High |
| **SHIPPING** | `shipping_delay`, `shipping_tracking`, `shipping_damage` | Low–Medium |
| **INVOICE** | `invoice_request`, `invoice_dispute`, `invoice_correction` | Medium |
| **CANCELLATION** | `cancellation_request`, `cancellation_fee`, `cancellation_policy` | Medium |
| **FEEDBACK** | `complaint`, `compliment`, `suggestion` | Low |
| **CONTACT** | `contact_human`, `contact_info`, `contact_callback` | Low |
| **TECHNICAL** | `technical_issue`, `technical_setup`, `technical_integration` | Medium |
| **GENERAL** | `general_inquiry`, `faq` | Low |
| **NEWSLETTER** | `newsletter_subscribe`, `newsletter_unsubscribe` | Low |

---

## 12. Configuration Reference

All settings are managed via environment variables, loaded through Pydantic `BaseSettings` with `.env` file support.

<details>
<summary><strong>🔧 Application</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `local` | `local`, `staging`, `production` |
| `APP_NAME` | `decision-platform` | Application name |
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |
</details>

<details>
<summary><strong>📊 Observability</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_ENABLED` | `true` | Prometheus `/metrics` |
| `TRACING_ENABLED` | `false` | OpenTelemetry tracing |
| `OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC endpoint |
| `OTLP_INSECURE` | `true` | Allow insecure gRPC |
| `TRACE_SAMPLE_RATIO` | `1.0` | Sampling ratio (0.0–1.0) |
| `OBSERVABILITY_LOG_FORMAT` | `json` | Log format |
| `OBSERVABILITY_SERVICE_NAME` | `decision-api` | Service name |
</details>

<details>
<summary><strong>💾 Database</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_POSTGRES` | `false` | Enable PostgreSQL |
| `POSTGRES_DSN` | `postgresql+psycopg://postgres:postgres@localhost:5432/decision_db` | DSN |
| `RETRIEVAL_VECTOR_DIM` | `64` | pgvector dimension |
| `RETRIEVAL_RRF_K` | `60` | RRF k parameter |
| `USE_REDIS` | `false` | Enable Redis |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis DSN |
</details>

<details>
<summary><strong>🔒 Security</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `false` | JWT authentication |
| `JWT_SECRET_KEY` | `change-me-local-dev-secret` | JWT signing key |
| `JWT_ALGORITHM` | `HS256` | Algorithm |
| `JWT_ISSUER` | `decision-platform` | Expected issuer |
| `JWT_AUDIENCE` | `decision-api` | Expected audience |
| `RATE_LIMIT_ENABLED` | `false` | Rate limiting |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window duration |
| `RATE_LIMIT_TENANT_REQUESTS_PER_WINDOW` | `120` | Per-tenant limit |
| `RATE_LIMIT_USER_REQUESTS_PER_WINDOW` | `60` | Per-user limit |
| `RATE_LIMIT_FAIL_OPEN` | `true` | Continue on Redis failure |
| `PII_REDACTION_ENABLED` | `true` | PII masking |
| `PROMPT_INJECTION_ENABLED` | `true` | Injection scanning |
| `PROMPT_INJECTION_THRESHOLD` | `0.60` | Risk threshold |
| `SECRETS_BACKEND` | `env` | `env` or `vault` |
| `VAULT_ADDR` | `` | Vault address |
</details>

<details>
<summary><strong>🤖 ML / Models</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `ROUTING_MODEL_BACKEND` | `heuristic` | `artifact`, `http`, `heuristic` |
| `MODEL_ARTIFACT_PATH` | `artifacts/models/routing_model.json` | Artifact path |
| `MODEL_SERVING_URL` | `http://localhost:9000` | Model server URL |
| `MODEL_TEMPERATURE` | `1.0` | Softmax temperature |
| `GENERATION_BACKEND` | `template` | `template` or `ollama` |
| `GENERATION_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama URL |
| `GENERATION_OLLAMA_MODEL` | `qwen2.5:7b-instruct` | LLM model |
| `EMBEDDING_BACKEND` | `local` | `local`, `sentence-transformer`, `api` |
| `MODEL_SHADOW_ENABLED` | `false` | Shadow evaluation |
| `CANARY_ROLLOUT_ENABLED` | `false` | Canary split |
| `CANARY_ROLLOUT_PERCENT` | `10` | Default canary % |
</details>

<details>
<summary><strong>📏 Confidence & Policy</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_CONFIDENCE_THRESHOLD` | `0.65` | Below → abstain |
| `MAX_AUTO_ESCALATION_PROB` | `0.55` | Above → escalate |
| `CONFIDENCE_WEIGHT_ROUTE` | `0.45` | Route weight |
| `CONFIDENCE_WEIGHT_EVIDENCE` | `0.25` | Evidence weight |
| `CONFIDENCE_WEIGHT_ESCALATION` | `0.20` | Escalation weight |
| `CONFIDENCE_PENALTY_OOD` | `0.07` | OOD penalty |
| `CONFIDENCE_PENALTY_CONTRADICTION` | `0.03` | Contradiction penalty |
| `OPA_URL` | `` | OPA endpoint |
</details>

<details>
<summary><strong>✅ Quality Gates & Guardrails</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_OPS_ROUTE_ACCURACY_GATE` | `0.75` | Min accuracy |
| `MODEL_OPS_ESCALATION_RECALL_GATE` | `0.70` | Min recall |
| `MODEL_OPS_CALIBRATION_ECE_GATE` | `0.15` | Max ECE |
| `MODEL_OPS_ABSTAIN_RATE_GATE` | `0.35` | Max abstain |
| `MODEL_OPS_MIN_SAMPLE_GATE` | `200` | Min samples |
| `MODEL_GUARDRAIL_FALLBACK_FORCE_HANDOFF` | `true` | Handoff on fallback |
| `MODEL_GUARDRAIL_CONFIDENCE_LOWER_BOUND` | `0.10` | Min confidence |
| `MODEL_GUARDRAIL_CONFIDENCE_UPPER_BOUND` | `0.99` | Max confidence |
</details>

<details>
<summary><strong>🔌 Integrations</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `EVENT_BUS_BACKEND` | `noop` | `noop` or `pubsub` |
| `PUBSUB_PROJECT_ID` | `` | GCP project ID |
| `PUBSUB_TOPIC_DECISIONS` | `decision-events` | Decisions topic |
| `PUBSUB_TOPIC_HANDOFFS` | `handoff-events` | Handoffs topic |
| `WORKFLOW_BACKEND` | `noop` | `noop` or `temporal` |
| `TEMPORAL_TARGET_HOST` | `localhost:7233` | Temporal host |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `TEMPORAL_TASK_QUEUE` | `assist-handoffs` | Task queue |
| `DATA_RETENTION_INFERENCE_DAYS` | `180` | Inference retention |
| `DATA_RETENTION_FEEDBACK_DAYS` | `365` | Feedback retention |
</details>

---

## 13. Getting Started

### Prerequisites

- Python 3.13+
- Docker & Docker Compose (for databases)
- Make (optional)

### Quick Start

```bash
# 1. Clone
git clone <repository-url>
cd decision-platform-baseline

# 2. Install dependencies
make setup
# Or: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 3. Start infrastructure
make docker-up
# Or: docker compose up -d

# 4. Initialize database
make init-db
# Or: python -m scripts.migrate && python -m scripts.seed_db

# 5. Generate dev JWT token
make gen-token
# Or: python -m scripts.generate_token

# 6. Start API server
make run-api
# Or: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### First Request

```bash
# Health check
curl http://localhost:8000/health
# → {"status": "ok"}

# Decision request (replace $TOKEN with step 5 output)
curl -X POST http://localhost:8000/v1/assist/decide \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "tenant_id": "acme-corp",
    "issue_text": "My order has not arrived and it has been 2 weeks",
    "section": "shipping",
    "risk_level": "medium"
  }'
```

### Zero-Dependency Mode

No Docker? No problem. The platform runs entirely in-memory:

```bash
make setup
make run-api
# That's it — in-memory stores, heuristic routing, template generation.
```

### Full Observability Stack

```bash
docker compose --profile observability up -d

# Grafana:      http://localhost:3000  (admin/admin)
# Prometheus:   http://localhost:9090
# Jaeger:       http://localhost:16686
# Alertmanager: http://localhost:9093
```

### MCP Server (AI Assistant Integration)

```bash
make run-mcp
# Exposes decision pipeline as AI tool calls via Model Context Protocol
```

---

## 14. Project Structure

```
decision-platform-baseline/
├── app/                              # Main application
│   ├── main.py                       # FastAPI entrypoint
│   ├── api/
│   │   ├── routes.py                 # All HTTP endpoints
│   │   └── deps.py                   # Dependency injection factory
│   ├── core/
│   │   └── config.py                 # 100+ Pydantic settings
│   ├── integrations/
│   │   ├── event_bus.py              # Noop / Pub/Sub events
│   │   └── workflow.py               # Noop / Temporal workflows
│   ├── models/
│   │   ├── schemas.py                # Request/response models
│   │   └── intent_taxonomy.py        # 30-intent taxonomy
│   ├── observability/
│   │   ├── logging.py                # Structured JSON logging
│   │   ├── metrics.py                # 25+ Prometheus metrics
│   │   ├── middleware.py             # Request middleware
│   │   └── tracing.py               # OpenTelemetry + Jaeger
│   ├── security/
│   │   ├── auth.py                   # JWT + RBAC
│   │   ├── output_validation.py      # Post-generation checks
│   │   ├── prompt_injection.py       # 3-layer defense
│   │   ├── rate_limit.py             # Redis token-bucket
│   │   └── secrets.py                # Env / Vault providers
│   ├── services/
│   │   ├── orchestrator.py           # Core pipeline (606 lines)
│   │   ├── routing.py                # Route + OOD + contradiction
│   │   ├── model_serving.py          # 4 model engines
│   │   ├── retrieval.py              # Hybrid search (309 lines)
│   │   ├── generation.py             # Template / Ollama (656 lines)
│   │   ├── policy.py                 # OPA / local rules
│   │   ├── handoff.py                # Escalation builder
│   │   ├── model_registry.py         # Lifecycle + lineage
│   │   └── readiness.py              # Health probes
│   ├── storage/
│   │   ├── postgres_store.py         # pgvector + FTS retrieval
│   │   ├── in_memory_store.py        # JSON fallback
│   │   ├── inference_store.py        # Audit persistence
│   │   ├── feedback_store.py         # Feedback events
│   │   ├── handoff_store.py          # Handoff queue
│   │   └── model_ops_store.py        # Shadow + rollout
│   └── utils/
│       ├── embedding.py              # 3 embedding backends
│       ├── pii_redaction.py          # 13-pattern masking
│       ├── rag_eval.py               # RAG quality metrics
│       └── circuit_breaker.py        # Circuit breaker
├── model_server/                     # Standalone model server (port 9000)
├── mcp_server/                       # MCP AI tool server
├── scripts/                          # 25+ operational scripts
├── artifacts/                        # Models + datasets + reports
├── migrations/                       # 10 PostgreSQL migrations
├── policy/                           # OPA Rego rules
├── infra/                            # Helm chart + Terraform + kind
├── observability/                    # Prometheus + Grafana + Alertmanager
├── tests/                            # Test suite
├── docs/                             # Extended documentation
├── .github/workflows/                # 5-stage CI/CD
├── docker-compose.yml                # 8 services, 4 profiles
├── Dockerfile                        # API container
├── Makefile                          # 55+ targets
├── requirements.txt                  # Core deps
└── requirements-optional.txt         # Optional deps
```

---

## 15. Makefile Commands

### Development

| Command | Description |
|---------|-------------|
| `make setup` | Create virtualenv + install all dependencies |
| `make run-api` | Start API with hot-reload |
| `make run-model-serving` | Start model server (port 9000) |
| `make run-mcp` | Start MCP server |
| `make test` | Run full test suite |
| `make lint` | Static analysis |
| `make gen-token` | Generate dev JWT |

### Database

| Command | Description |
|---------|-------------|
| `make docker-up` | Start Postgres + Redis |
| `make docker-down` | Stop all containers |
| `make init-db` | Migrate + seed |
| `make migrate-db` | Run migrations |
| `make seed-db` | Seed data |

### Model Operations

| Command | Description |
|---------|-------------|
| `make evaluate-daily` | Daily model evaluation |
| `make evaluate-metrics` | Compute metrics |
| `make drift-check` | Drift detection |
| `make recalibrate-models` | Recalibrate thresholds |
| `make promote-canary` | Promote canary → production |
| `make model-ops-daily` | Full daily pipeline |
| `make production-readiness-gate` | Pre-deploy quality check |

### Operations

| Command | Description |
|---------|-------------|
| `make business-scorecard` | Business KPIs |
| `make oncall-audit` | Audit on-call config |
| `make security-audit` | Compliance audit |

### Kubernetes

| Command | Description |
|---------|-------------|
| `make k8s-local-deploy` | Deploy to local kind |
| `make k8s-local-teardown` | Tear down cluster |
| `make k8s-local-redeploy` | Rebuild + redeploy |

### Data Pipeline

| Command | Description |
|---------|-------------|
| `make bitext-pipeline` | Download + import Bitext data |
| `make import-retrieval-seed` | Import knowledge base |
| `make reindex-embeddings` | Re-embed all chunks |

---

<p align="center">
  <strong>Built for production-grade AI decision making</strong><br/>
  <sub>Classify · Retrieve · Score · Decide · Generate · Learn</sub>
</p>


---

### Developed by Hemanth Sai D