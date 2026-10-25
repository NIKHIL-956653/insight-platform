# ADR-001 — Platform stack

- **Status:** Accepted
- **Decided:** 2026-10-25
- **Decision maker:** Nirun (Pro Tech), Product Owner, with Thretrix as implementer

## Context

InSight handles board material: financial models, strategy memos, deal documents. The
non-negotiables are tenant isolation, provable auditability, and citations that can be
trusted by executives. Pro Tech has locked seven decisions and defined a four-criterion
acceptance gate for R1.

The engagement also has a budget constraint: no tooling spend has been allocated. Pro Tech
has endorsed building on free and open-source infrastructure, with paid certification
deferred until budget exists.

## Decisions

### 1. Two authorization layers, not one

PostgreSQL Row-Level Security enforces hard workspace isolation at the database layer.
SpiceDB handles fine-grained document and meeting permissions within a workspace.

A `WHERE workspace_id = :current` clause in application code is not equivalent. RLS is
enforced by the database for every query, including ones a future developer forgets to
filter, and including raw SQL. Isolation that depends on remembering to filter is not
isolation.

The audit log additionally uses a separate INSERT-only database role, so application code
cannot rewrite history even if compromised.

### 2. Free and open-source infrastructure

| Layer | Choice |
|---|---|
| Database, vectors | PostgreSQL + pgvector |
| Vector store (alternate) | Qdrant |
| Cache, streams | Redis |
| Fine-grained authz | SpiceDB |
| Observability | Langfuse, self-hosted |
| Embeddings | Ollama + `nomic-embed-text`, 768-dim |
| Reranking | BGE cross-encoder, CPU |
| Keyword retrieval | BM25 via Qdrant sparse vectors or Postgres FTS |
| Generation, development | Local model behind LiteLLM |
| Speech, development | Whisper + pyannote |
| Test identity provider | Keycloak |
| Exports | WeasyPrint, python-docx |
| Kubernetes | k3s / kind |

These are the enterprise tools, not downgrades. Paid tiers of this stack sell hosting
convenience, not capability.

Langfuse is self-hosted and not the SaaS offering. The hosted version would transmit board
prompts outside the client tenancy, which violates locked decision 2.

### 3. Permissive licences only

Every runtime dependency is BSD, MIT or Apache-2.0.

PyMuPDF is the conventional choice for PDF extraction and was rejected: it is AGPL-3.0.
Shipping it in delivered software would oblige Thretrix either to offer the entire platform's
source under AGPL or to buy a commercial licence. `pypdf` combined with `pdfplumber` provides
the page-anchored extraction that gate criterion 3 requires, under BSD and MIT.

This constraint applies to every future dependency. Check the licence before adding one.

### 4. Model selection is configuration, never code

No model name appears in source. All selection lives in LiteLLM gateway configuration,
routed per feature. The four slots:

| Slot | Model |
|---|---|
| Development generation | Local, via Ollama |
| Production generation | Client tenancy — Bedrock or Azure OpenAI |
| Embeddings | `nomic-embed-text` in development |
| Gate 3 certification | A frontier model, one run, deferred |

Moving between them is a configuration change.

The embedding model name **and dimension** are stored alongside every vector. A mismatch is
then detectable rather than silently returning meaningless nearest neighbours.

### 5. Three processes

A modular monolith for the core API, plus separate Ingestion and Durable Background Worker
services. Ingestion and long-running simulator phases must not compete with request handling,
and the worker needs phase-level checkpointing that a request lifecycle cannot provide.

### 6. Tests never make live model calls

The suite mocks at the transport layer with `respx`. Tests therefore cost nothing, run
offline, and are deterministic. A test that depends on a live model is not a test.

## Consequences

**Accepted:**

- The full scope of all eight modules is built. The free stack changes tooling, not scope.
- Gate criteria 1, 2 and 4 are fully achievable on this stack and must pass on it.
- Gate criterion 3 is built and scored locally, but certification is deferred. Local models
  fabricate citations; that is their characteristic failure and precisely what this gate
  measures. Recorded in `KNOWN_LIMITATIONS.md`.

**Risks:**

- **Embedding model choice is the one decision that is not a configuration swap.** If
  production uses a model other than `nomic-embed-text`, the corpus requires a full re-index.
  Confirm with Pro Tech before indexing at scale.
- Local generation quality is below production. Prompt engineering tuned against a local
  model may not transfer cleanly.
- Three items need Pro Tech's own infrastructure and were never within Thretrix's gift at any
  budget: in-tenancy inference, production SSO against their identity provider, and the R3
  managed speech vendor contract.

## The seven locked client decisions

1. Nirun (Pro Tech) is Product Owner with final sign-off on architecture and gates. Standing
   weekly architecture and demo review.
2. Production storage, vector indexing and inference stay inside the client's cloud tenancy
   under their zero-data-retention agreements. Development runs on client-supplied keys
   against redacted data, with PII/secret redaction and prompt-injection guardrails active in
   the gateway from R1.
3. PostgreSQL RLS for hard workspace isolation; SpiceDB strictly for fine-grained document
   and meeting permissions within a workspace.
4. Modular monolith for the core backend, plus separate Ingestion and Durable Background
   Worker services.
5. Hash-chained tamper-evident logs and transcripts, seven-year retention, crypto-shredding
   of sensitive payload fields so deletion requests never break the chain.
6. R3 speech uses a managed vendor (Deepgram Nova or Azure AI Speech), chosen by bake-off
   before R3 planning. Recurring vendor costs sit with the client.
7. Three redacted board packs — a 50+ page PDF deck, a financial XLSX, a DOCX memo — form the
   ground-truth evaluation corpus. R3 web search strips confidential company and deal names
   and is restricted to an approved domain allow-list.
