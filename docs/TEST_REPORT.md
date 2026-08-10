# Test report — checkpoint B0.2A

## Environment

| Field | Value |
| --- | --- |
| Date | 2026-08-10 |
| OS | Windows 10 (build 26200) |
| Python | 3.x (project constraint `>=3.11,<3.14`) |
| Docker | not used |
| Network for default suite | not required |

## Commands

```powershell
python -m pytest tests -q
python scripts\validate_contracts.py
python scripts\validate_knowledge.py --scope offline-fixture --strict
python scripts\run_b0.py --split development --provider fake --run-id release-fake-b02a-001
python scripts\run_b0.py --split development --provider gemini --run-id release-gemini-preflight --preflight `
  --query-id P-DEV-01-Q01 --query-id P-DEV-02-Q01 --query-id SEC-DEV-01-Q01 --budget-usd 0.25
```

## Results

| Check | Result |
| --- | --- |
| `pytest tests -q` | **116 passed** |
| Contract validation | PASSED |
| Knowledge validation (offline-fixture, strict) | PASSED |
| Production readiness | **NOT_READY** (expected) |

### FakeLLM smoke (`release-fake-b02a-001`)

```text
scenarios_run=12
queries_run=30
traces_written=30
missing_trace=0
initial_tickets_seeded=5
scenario_isolation_violations=0
cross_user_leakage=0
invalid_transition_executed=0
fake_fixture_coverage=30/30
quality_claim=false
estimated_cost_usd=0.0
policy allow/deny/clarify/none=13/2/2/13
```

FakeLLM / fixture accuracy is **infrastructure validation only**, not Gemini quality.

### Gemini preflight

```text
status=preflight_ok
network_called=false
live_enabled=false
api_key_present=false
```

## Protected hashes

```text
scenarios_eval.yaml
dad9348245d46327f980f0221589f8a99fc3d9781e4f03a99682057ab7924be6

corpus_manifest.csv
ea9122c6c356b6f8715de5d05ac2679fa4fa945d47c3a7faacb141da3eac436c

staged_bundle_sha256
860996a1460a905664cd87521c31510a5a5dfc0e8a9b1f077fd50600723b71cf

promotion_status=staged_pending_research_approval
approved_bundle_sha256=null
```

## Safety statement

```text
gemini_called=false
api_cost_usd=0
live_fetch_called=false
production_published=false
research_approval_modified=false
scenarios_eval_mutated=false
quality_claim=false
```
