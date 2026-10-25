# Known limitations

Recorded honestly, as they stand. Nothing here is hidden from Pro Tech.

---

## 1. R1 gate criterion 3 is not certified

**Status:** deferred, tracked, not dropped.

The citation-grounding gate requires at least 95% of factual and financial claims to resolve
to the correct source document and page, with zero fabricated citations.

The evaluator is **built and running**. The pipeline that produces the citations is built. The
score is produced on every run. What is deferred is *certification against a frontier model*.

Local 7B-class models fabricate citations. That is their characteristic failure mode, and it
is exactly what this gate measures. A local score is therefore real information about the
retrieval pipeline but is **not** a pass on this criterion, and will not be reported as one.

**To certify:** change the generation model in the LiteLLM gateway configuration and re-run
the Grounding Evaluator. Roughly $150. No code changes, no rebuild.

**Current local score:** not yet measured — INS-31 has not been built.

| Gate criterion | Passes on free stack? |
|---|---|
| 1 — hard tenant isolation | Yes |
| 2 — audit chain integrity | Yes |
| 3 — citation grounding | Built and scored; certification deferred |
| 4 — zero-loss reconnection | Yes |

---

## 2. Embedding model choice is not a configuration swap

This is the one architectural decision on the project that cannot be reversed cheaply.

Development uses Ollama `nomic-embed-text` at 768 dimensions. If production uses a different
embedding model, the vector space and dimensionality differ and **the entire corpus must be
re-indexed**. Swapping the generation model is a config line; swapping the embedding model is
a re-index.

**Mitigation in place:** the embedding model name and dimension are stored alongside every
vector, so a mismatch is detected rather than silently returning meaningless results.

**Open question for Pro Tech:** which embedding model does production use? This should be
answered before indexing at scale.

---

## 3. Local generation quality is below production

Prompts tuned against a local model may not transfer cleanly to the production model. Brief
quality, adversarial simulator personas and judge-then-generate behaviour will all need
re-tuning once production inference is available.

This is a known cost of developing without production model access, not a defect.

---

## 4. Three items depend on Pro Tech's infrastructure

These were never within Thretrix's gift at any budget. They are blocked on client
provisioning, not on money or effort:

| Item | Needs |
|---|---|
| In-tenancy inference and storage | Pro Tech's Azure or AWS tenancy, their ZDR agreements |
| Production SSO | Pro Tech's real Entra or Okta tenant. Keycloak proves the integration; their tenant completes it |
| R3 managed speech vendor | Pro Tech's contract with Deepgram or Azure AI Speech, per locked decision 6 |

---

## 5. Compliance obligations are unanswered

Whether Pro Tech requires SOC 2 or ISO 27001 alignment has been asked across four messages
and not answered. This affects R1 design decisions, not only the R4 handover — control
evidence is far cheaper to produce as you build than to retrofit.

Currently proceeding without a compliance framework assumption.
