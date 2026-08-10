# Architecture

## Offline corpus flow

```text
Public HTML / regulated assets
  → fetch (gated) / materialize
  → artifacts/live_staging (manifest + 18 by_source JSON)
  → bundle digest (excludes provenance JSON)
  → Research approve (binds approved_bundle_sha256)
  → publish-existing (no restage/fetch)
  → data/corpus production snapshots + catalog review
```

Committed flags keep `live_fetch_enabled=false` and `publish_enabled=false`. Staging may be present with `promotion_status=staged_pending_research_approval` and `approved_bundle_sha256=null`.

## Online query flow (B0)

```text
CLI / Experiment Runner
  → per-scenario SQLite DB
  → seed initial_state.ticket_store (SEED events)
  → Conversation Orchestrator
      → LLM Client (Fake | Gemini) proposes StructuredAction + usage metadata
      → Policy Engine (identity, lookup, transitions, hard gates)
      → Ticket Service (state machine enforced again)
      → SQLite transaction
      → Execution Trace + run-scoped Cost Ledger
```

## Authority boundaries

| Component | May do | Must not do |
| --- | --- | --- |
| LLM | Propose structured action | Write SQLite; own tickets; bypass policy |
| Policy Engine | ALLOW / DENY / CLARIFY / NONE | Mutate DB |
| Ticket Service | Mutate tickets/events | Trust LLM `user_id` |
| Cost Guard | Authorize/reject spend | Reset mid-run |

Trusted identity always comes from execution context. Cross-user and unknown tickets fail closed at Policy with generic public messages.

## Ticket Store vs MAG Memory

B0 uses **Ticket Store only**. `initial_state.memory_store` is ignored (`memory_enabled=false`). MAG Memory Store is reserved for later baselines (B3/B4) and remains out of scope for B0.2A.

## Gemini structured-action boundary

Gemini is asked for versioned JSON (`structured_action_v1`) validated by Pydantic into `StructuredAction`. Invalid schema → no Ticket Service call, one trace with typed error. Live calls require independent gates (`gemini.live_enabled`, `--allow-paid`, confirmation token, budget, query allowlist). Default: locked.
