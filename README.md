# Green SM-inspired RAG–MAG PoC

Reproducible research PoC for post-trip customer-support assistants. The project uses **public Green SM help/policy pages** and **synthetic personas/scenarios only**. It is **not** Green SM production software and does **not** connect to production systems.

## Checkpoint status — B0.2A

| Item | Status |
| --- | --- |
| Offline corpus pipeline + governance (Pass B.1.1) | Approved |
| B0.1 runtime correctness (isolation, policy, ticket SM) | Approved |
| B0.2A Gemini provider (structured output, cost gates) | Complete **offline** |
| Live Gemini canary | **Not run** (`gemini.live_enabled=false`) |
| Production corpus READY | **NOT_READY** (awaits Research approval) |
| RAG / MAG baselines (B1–B4) | Not started |

**FakeLLM / mock Gemini results are infrastructure evidence only — not model-quality claims.**

## Problem statement

Support agents must answer policy questions and mutate tickets safely. The PoC evaluates whether an LLM can propose structured ticket actions under a fail-closed Policy Engine, with Ticket Store as system of record — before adding RAG and memory-augmented generation.

## What is complete

- Governed 18-unit corpus contract, staging bundle digest, publish-existing workflow (flags locked off).
- B0 runtime: SQLite Ticket Store, Policy Engine, shared state machine, scenario isolation, FakeLLM fixtures (30/30).
- B0.2A: official `google-genai` adapter, versioned prompt/schema, run-scoped cost ledger, CLI live gates + preflight.

## What is not complete

- Live Gemini canary / paid calls.
- Research catalog approval → production READY.
- RAG retrieval (B1), MAG memory (B3/B4), OCR for image-only terms.
- Held-out evaluation scoring as a research deliverable.

## Architecture (summary)

```text
CLI / Runner → Orchestrator → LLM (Fake | Gemini)
                           → StructuredAction
                           → Policy Engine
                           → Ticket Service → SQLite
                           → Trace + Cost Ledger
```

LLM never writes SQLite. Trusted `user_id` comes from execution context only. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Baseline roadmap

| Baseline | Description |
| --- | --- |
| **B0** | LLM + Ticket + Policy (this checkpoint) |
| **B1** | RAG + Ticket |
| **B2** | Naive vector memory + Ticket (stretch) |
| **B3** | Lifecycle MAG + Ticket |
| **B4** | RAG + Lifecycle MAG + Ticket |

## Repository structure

```text
config/       experiment, policy, gemini gates, corpus snapshot flags
data/         personas, scenarios, corpus contract/manifest/snapshots/catalog
docs/         executive + technical documentation
schemas/      JSON Schema contracts
scripts/      validation and B0 runner CLIs
src/          poc_contracts, poc_corpus, poc_runtime
tests/        offline unit/integration + fixtures
artifacts/    live_staging (governed; pending Research approval)
```

## Environment

- Windows (primary)
- Python `>=3.11,<3.14`
- RAM ≤ 8 GB
- **No Docker**
- No network required for default tests / FakeLLM smoke

## Install (PowerShell)

```powershell
git clone https://github.com/NguyenTrongNguyen04/PoC_GSM.git
cd PoC_GSM
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` → `.env` only if you later run an approved paid canary. Never commit `.env`.

## Validate and test

```powershell
python scripts\validate_contracts.py
python scripts\validate_knowledge.py --scope offline-fixture --strict
python -m pytest tests -q
```

## FakeLLM B0 smoke

```powershell
python scripts\run_b0.py --split development --provider fake --run-id demo-fake-smoke-001
```

Use a **new** `--run-id` each time (existing IDs are refused).

## Gemini preflight (zero network)

```powershell
python scripts\run_b0.py --split development --provider gemini --run-id demo-gemini-preflight --preflight `
  --query-id P-DEV-01-Q01 --query-id P-DEV-02-Q01 --query-id SEC-DEV-01-Q01 --budget-usd 0.25
```

Live Gemini stays locked until Research enables `config/gemini.yaml` → `live_enabled: true` and supplies CLI confirmation. This checkpoint does **not** run live calls.

## Data governance and privacy

- Synthetic personas only; no real PII, tickets, or trip history.
- Evaluation split (`scenarios_eval.yaml`) is sealed; do not mutate.
- Corpus publish and Research approval are human ceremonies — not automated by CI.
- `live_fetch_enabled=false`, `publish_enabled=false` in committed config.

## Reproducibility

- Pinned dependencies in `requirements.txt` / `requirements-dev.txt`.
- Deterministic FakeLLM fixtures under `tests/fixtures/b0/`.
- Per-scenario SQLite under unique run directories.
- Protected SHA-256 hashes documented in [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## Known limitations

- Production corpus `NOT_READY`.
- Model ID `gemini-3.5-flash-lite` is config-locked with `model_runtime_validation=pending_canary`.
- Pricing snapshot is estimation-only until re-verified before paid canary.
- FakeLLM accuracy is not Gemini quality.

## Safety statement

```text
gemini_called=false
api_cost_usd=0
live_fetch_called=false
production_published=false
quality_claim=false
```

## Documentation

- [SUBMISSION.md](SUBMISSION.md) — management submission page
- [docs/EXECUTIVE_SUMMARY.md](docs/EXECUTIVE_SUMMARY.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/EVALUATION_PLAN.md](docs/EVALUATION_PLAN.md)
- [docs/TEST_REPORT.md](docs/TEST_REPORT.md)
- [docs/DECISION_LOG.md](docs/DECISION_LOG.md)
- [docs/TECHNICAL_BACKLOG.md](docs/TECHNICAL_BACKLOG.md)
- [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md)
- [docs/IMPLEMENTATION_SPEC.md](docs/IMPLEMENTATION_SPEC.md)
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [NOTICE.md](NOTICE.md)
