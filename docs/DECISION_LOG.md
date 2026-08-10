# Decision Log

## 2026-08-10 — B0.2A Gemini provider integration (offline)

Implemented Gemini adapter using official `google-genai==2.17.0` (docs verified 2026-08-10; **no live API call**). Added versioned prompt/schema (`b0_action_v1` / `structured_action_v1`), typed `LLMCallResult`, typed provider errors, transient-only retry with injected sleeper, run-scoped CostGuard ledger, CLI live gates + `--preflight`, MockGeminiTransport for offline tests. Model ID remains `gemini-3.5-flash-lite` with `model_runtime_validation=pending_canary`. `gemini.live_enabled=false`. Corpus/eval untouched.

## 2026-08-10 — B0.1 runtime correctness

Research-approved remediation for Day 2/B0 harness:

1. Shared `TicketStateMachine` from `config/policy.yaml`; Ticket Service enforces transitions (OPEN→CLOSED blocked).
2. Typed ticket lookup (`FOUND`/`NOT_FOUND`/`ACCESS_DENIED`/`NOT_REQUESTED`); Policy fail-closed; no silent `TicketError` swallow.
3. Per-scenario SQLite DBs; seed `initial_state.ticket_store` with `SEED` events (not LLM actions); scenario clock injection.
4. Experiment run isolation via `artifacts/b0_runs/{run_id}/`; refuse existing run_id; no shared mutable DB.
5. Deterministic FakeLLM fixtures (`tests/fixtures/b0/fake_actions_dev.yaml`) with 30/30 coverage; evaluation metrics post-inference only; `quality_claim=false`.

Corpus / eval / production untouched. Production remains `NOT_READY`.

## 2026-08-10 — Day 2 / Baseline B0 (FakeLLM offline)

Implemented local B0 runtime under `src/poc_runtime/`: SQLite Ticket Store, Ticket Service, Policy Engine, FakeLLM + Gemini scaffold (no live calls), Cost Guard (hard cap $15; fake=$0), Conversation Orchestrator, Trace writer, CLI `scripts/run_b0.py`. No RAG/MAG/embeddings. LLM never writes SQLite directly. Eval split untouched; development smoke uses FakeLLM only.

## 2026-08-10 — Pass B.1.1 locked remediations

### Context
Research Lead conditionally approved Pass B.1 to open Day 2, with four remediations. Production remains NOT_READY; Code Lead must not forge approval/publish/READY.

### Implemented
1. Immutable `staged_bundle_sha256` / `approved_bundle_sha256` over staging manifest + 18 snapshot raw-byte hashes (provenance excluded from digest). Publish recomputes and REFUSES post-approval mutation.
2. `--publish-existing STAGING_DIR` publishes without stage/fetch; mutually exclusive with `--mode`.
3. CORPUS spans corrected (still `candidate_live`):
   - `INVOICE_GUIDANCE` → post-trip request-deadline notes
   - `CANCELLED_CHARGE_GUIDANCE` → bank statement check + support channel
4. Development ground-truth: `H-DEV-02-Q01` adds `GSM-HELP-SUPPORT-604`; `scenarios_dev.yaml` `dataset_version` 0.1.0 → 0.1.1. Eval split untouched.

### Still forbidden until Research publish ceremony
Forge approval, production publish, READY declaration, live fetch with flags locked.

## 2026-08-10 — Pass B.1 governance remediation

Bundle provenance, candidate_live catalog, publish gates, materializer v0.2 (see prior handoff).
