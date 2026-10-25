# InSight Platform

Enterprise meeting intelligence. A board pack goes in; fully cited pre-meeting briefs, live
in-meeting insights and post-meeting minutes come out — plus a five-phase multi-agent
simulator that war-games board decisions through CFO, Skeptic, Legal and Strategy personas,
a real-time voice and chat assistant, and enterprise governance throughout.

Built by **Thretrix** for **Pro Tech**. Private repository — see [Confidentiality](#confidentiality).

---

## Releases

Four gated releases. Each is independently demonstrable and is accepted against stated
criteria before the next begins. Delivery is gated on acceptance, not scheduled against dates.

| Release | Delivers |
|---|---|
| **R1** | Grounded foundation — multi-tenant auth, hybrid RAG with cited briefs, zero-loss streaming backbone, tamper-evident audit, LLM gateway, portal shell |
| **R2** | Full meeting lifecycle (pre / live / post), five-phase simulator with durable checkpointing, full Evals service |
| **R3** | Real-time voice, diarization, live captions, phase-aware chat with tool orchestration |
| **R4** | Enterprise SSO, admin and governance console, board-ready exports, Kubernetes handover |

## Architecture

Three processes, per locked decision 4:

| Process | Entry point | Role |
|---|---|---|
| API | `insight-api` | Modular-monolith FastAPI backend |
| Ingestion | `insight-ingest` | Document parsing, chunking, embedding |
| Worker | `insight-worker` | Durable background jobs with checkpointing |

Two independent authorization layers, deliberately not one:

- **PostgreSQL RLS** — hard workspace isolation enforced at the database layer
- **SpiceDB** — fine-grained document and meeting permissions *within* a workspace

## Local development

Prerequisites: Python 3.13, Docker Desktop, Ollama.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"

Copy-Item .env.example .env   # then fill in the secrets

docker compose -f infra/docker-compose.yml up -d
alembic upgrade head
insight-api
```

Quality gates:

```powershell
ruff check . ; ruff format --check .
mypy
pytest
```

## R1 acceptance gate

1. **Hard tenant isolation** — a user in Workspace A cannot read, query or retrieve Postgres
   rows, Redis stream events or vector chunks belonging to Workspace B.
2. **Audit chain integrity** — every mutation and AI output creates a hash-chained record
   where `verify_chain()` is true, and altering any historical entry fails verification.
3. **Citation grounding** — against the sample board packs, at least 95% of factual and
   financial claims resolve to the correct source document and page, with zero fabricated
   citations.
4. **Zero-loss reconnection** — dropping and reconnecting a WebSocket replays missed events
   from Redis Streams with no dropped segments.

Criterion 3 is built and scored on local models, but is formally certified against a frontier
model. See [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Confidentiality

Client board material is confidential and must never enter this repository or leave the
client tenancy.

- `*.pdf`, `*.docx`, `*.xlsx`, `*.pptx` are gitignored repo-wide; only `tests/fixtures/` is
  exempt. Once a confidential file is in git history it is effectively permanent.
- Langfuse is **self-hosted only**. The hosted version would send board prompts outside the
  client tenancy.
- Production storage, vector indexing and inference stay inside the client's cloud tenancy.
- The audit log is written through a separate INSERT-only database role, so application code
  cannot rewrite history even if compromised.

## Licensing

Proprietary. Every runtime dependency is BSD, MIT or Apache-2.0 — no copyleft. PyMuPDF was
rejected in favour of `pypdf` + `pdfplumber` for this reason; see
[ADR-001](docs/ADR-001-stack.md).

## Documentation

| Document | Contents |
|---|---|
| [`docs/ADR-001-stack.md`](docs/ADR-001-stack.md) | Stack choices and the decisions behind them |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | R1 ticket breakdown |
| [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) | What is deferred, and why |
