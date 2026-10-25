# Backlog — Release 1

Dependency-ordered. "Port" means lift working code from an existing repo rather than rewrite
it. Four tickets map directly to the R1 acceptance gate and are marked **GATE**.

## The discipline rule

> No new scope is added mid-ticket. Anything that arises goes in
> [Raised mid-release](#raised-mid-release) below and is reviewed at the gate — never folded
> into the ticket in flight.

Scope has already expanded twice on this engagement. The gates are what protect both sides.

## Tickets

| # | Ticket | Port |
|---|---|---|
| INS-1 | Scaffold: `pyproject.toml`, `.gitignore`, `.env.example`, README, ADR-001, backlog, known limitations | |
| INS-2 | `docker-compose`: Postgres + pgvector, Redis, Qdrant, SpiceDB, Langfuse self-hosted, Ollama | |
| INS-3 | Config via `pydantic-settings`; `structlog` JSON logging; `insight-api` entry point | |
| INS-4 | Async engine, session factory, `DeclarativeBase`, Alembic init | |
| INS-5 | `Workspace` and `User` models, first migration | |
| INS-6 | argon2 password hashing, `POST /v1/auth/login`, `GET /v1/auth/me` | |
| INS-7 | Short-lived access JWT, rotating refresh tokens, reuse detection | |
| INS-8 | PostgreSQL RLS policies, tenant context dependency, per-request `SET LOCAL` | eap |
| INS-9 | **GATE 1** — cross-tenant isolation integration test | eap |
| INS-10 | SpiceDB `.zed` schema, client wrapper, document and meeting permission checks | |
| INS-11 | Hash-chained audit log, separate INSERT-only database role | eap |
| INS-12 | **GATE 2** — `verify_chain()`, audit endpoints, tamper-detection test | eap |
| INS-13 | Crypto-shredding of sensitive payload fields without breaking the chain | |
| INS-14 | LiteLLM gateway, per-feature routing config, no hardcoded model names | |
| INS-15 | Circuit breaker and retry policy — one retry layer, ours, not the SDK's | eap |
| INS-16 | Guardrails: PII and secret redaction, prompt-injection detection | |
| INS-17 | Langfuse wiring — cost, latency, token and quality callbacks | |
| INS-18 | `Document` model, upload endpoint, storage abstraction | |
| INS-19 | Parsers: PDF, DOCX, XLSX to page-anchored text | |
| INS-20 | Parent-child chunking preserving page provenance | rag-curriculum |
| INS-21 | Ollama embeddings; model name and dimension stamped on every vector | |
| INS-22 | Dense retrieval over pgvector | rag-curriculum |
| INS-23 | Sparse BM25 retrieval | rag-curriculum |
| INS-24 | Reciprocal rank fusion, BGE cross-encoder rerank, top-50 to top-5 | rag-curriculum |
| INS-25 | Citation grounding — resolve each claim to exact document and page | |
| INS-26 | Durable worker, async ingestion pipeline, `insight-ingest` and `insight-worker` | |
| INS-27 | Redis Streams publisher, consumer groups, ACK tracking | |
| INS-28 | WebSocket fan-out, backpressure handling, active session registry | |
| INS-29 | **GATE 4** — reconnect replay from `last_event_id`, zero-loss test | |
| INS-30 | Board Brief and Agenda Summary generators, RAG-grounded | |
| INS-31 | **GATE 3** — Grounding and Citation Check runner, scored | |
| INS-32 | React + Vite portal shell: sign-in, workspace switcher, upload, Cited Brief view | |
| INS-33 | CI: ruff, mypy, pytest, coverage gate | eap |
| INS-34 | R1 gate demo script, `KNOWN_LIMITATIONS.md` updated | |

## Gate ticket acceptance criteria

### INS-9 — Gate 1, hard tenant isolation

A user authenticated into Workspace A must not be able to read, query or retrieve:

- Postgres rows belonging to Workspace B, including via raw SQL and via any endpoint
- Redis stream events published to Workspace B's streams
- Vector chunks indexed under Workspace B

Automated integration test. Must also prove that a query written *without* an explicit
workspace filter still returns nothing from Workspace B — that is the whole point of RLS over
application-level filtering.

### INS-12 — Gate 2, audit chain integrity

- Every mutation and every AI output creates a hash-chained audit record.
- `verify_chain()` returns true across the full chain.
- Modifying any historical entry causes verification to fail, and the test proves it by
  tampering deliberately.
- Crypto-shredding a payload field does not break the chain.

### INS-29 — Gate 4, zero-loss reconnection

Drop a WebSocket mid-stream, reconnect, and replay from `last_event_id`. No dropped segments,
no duplicates delivered as new, and backpressure does not silently discard events.

### INS-31 — Gate 3, citation grounding

Against the three redacted board packs:

- At least 95% of factual and financial claims resolve to the correct source document and page
- Zero fabricated document or page citations

Scored on local models during development; **formally certified against a frontier model
later**. The local score is recorded honestly in `KNOWN_LIMITATIONS.md` and is not presented
as a pass.

## Raised mid-release

Nothing yet. Items land here instead of being folded into the ticket in flight.

| Raised during | Item | Decision at gate |
|---|---|---|
| | | |
