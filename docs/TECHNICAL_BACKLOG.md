# Technical Backlog (non-blocking)

Items noted during Pass B.1.1 / Day 2 but **not** implemented in this turn:

- JSON Pointer / YAML path resolution hardening for all 34 non-CORPUS structured refs (beyond file existence).
- Rename catalog `reviewed_snapshot_sha256` → `reviewed_bundle_sha256` when Research wires catalog approval to bundle digest.
- Record auxiliary regulations JS URL/hash with MIME/size-validated script fetch in provenance (optional hardening).
- OCR pipeline for `GSM-TERMS-OPERATING` image-only assets.
- Auto-relock hooks after publish ceremony.
- Wire FakeLLM fixtures to per-query `expected_action` from scenarios for richer S0 scoring.
- Gemini live client behind explicit paid flag + cost guard integration (not in this turn).
- Persist policy reason_codes into ticket_events for audit dashboards.
- Align FakeLLM fixture answer phrasing review with Research for refund-adjacent wording edge cases.
- Live Gemini canary (3 queries, ≤$0.25) after Research Lead approval and `gemini.live_enabled=true`.
- Re-verify Gemini pricing snapshot immediately before paid canary.
- Confirm `gemini-3.5-flash-lite` availability at canary time (`model_runtime_validation=pending_canary`).
