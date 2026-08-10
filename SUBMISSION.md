# Submission — Green SM RAG/MAG PoC

## Project

Green SM-inspired customer-support evaluation PoC (public + synthetic data only).

## Business use case

Measure whether an assistant can answer post-trip support questions and propose ticket actions under policy constraints, before comparing RAG and memory-augmented baselines.

## Checkpoint

`checkpoint-b0.2a` — governed corpus through B0.1 runtime correctness and offline Gemini B0.2A provider integration.

## Completed scope

- Offline/live corpus pipeline with immutable bundle digest and publish-existing separation.
- B0.1: scenario isolation, initial-state seeding, shared ticket state machine, fail-closed cross-user policy.
- B0.2A: Gemini structured-action adapter, run-scoped cost ledger, CLI gates, offline mock/preflight tests.

## Key engineering results

- Ticket Store is system of record; LLM cannot write SQLite.
- Policy Engine stands between LLM proposals and Ticket Service.
- Live Gemini and corpus publish remain fail-closed by default.

## Test evidence

See `docs/TEST_REPORT.md` for the latest local validation numbers, FakeLLM smoke, and Gemini preflight (`network_called=false`).

## Current limitations

- B0.1 runtime is complete; B0.2A Gemini integration is complete **offline**.
- Live Gemini has **not** been run; API cost is **0**.
- RAG/MAG comparison is **not** complete.
- Production corpus still awaits Research approval (`NOT_READY`).
- No quality claim from FakeLLM or mock Gemini.

## How to reproduce

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python scripts\run_b0.py --split development --provider fake --run-id submit-fake-001
```

## Deliverables

- Private GitHub repository source + docs + offline CI.
- Annotated tag `checkpoint-b0.2a`.
- Governed `artifacts/live_staging` pending Research approval (`approved_bundle_sha256=null`).

## Next milestone

Research-approved 3-query Gemini canary (≤ $0.25), then B1 RAG — only after canary gates pass.

## Approval requested

Please review this private checkpoint for management acceptance of packaging and offline engineering completeness. Do **not** interpret this as production readiness or model-quality success.
