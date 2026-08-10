# Evaluation plan

## Dataset

- 8 synthetic personas
- 24 scenarios (12 development / 12 held-out)
- 60 query points total (30 development in current B0 harness)

Held-out scenarios live in `data/scenarios/scenarios_eval.yaml` and must not be mutated during implementation turns. Eval SHA is a release gate.

## Baselines

| ID | Description | Checkpoint |
| --- | --- | --- |
| B0 | LLM + Ticket + Policy | In progress (runtime + offline Gemini) |
| B1 | RAG + Ticket | Future |
| B2 | Naive vector memory + Ticket | Stretch |
| B3 | Lifecycle MAG + Ticket | Future |
| B4 | RAG + Lifecycle MAG + Ticket | Future |

Fairness: shared model/prompt shell/ticket/policy/budget across baselines once live evaluation begins.

## Metrics (planned)

- Action-type / policy-decision agreement vs sealed labels (post-inference only)
- Trace completeness (one trace per query)
- Hard gates: cross-user leakage = 0, invalid transition executed = 0
- Cost and latency summaries
- Human review sample on held-out (charter fraction)

## Inference hygiene

Ground truth fields (`expected_action`, `expected_facts`, `expected_doc_ids`, `forbidden_facts`, etc.) are **never** passed into the LLM prompt. Evaluation compares traces to labels after the fact. FakeLLM fixtures are test doubles, not labels.

## Canary (prepared, not executed at B0.2A)

```text
P-DEV-01-Q01   # NONE / FAQ
P-DEV-02-Q01   # CREATE_TICKET
SEC-DEV-01-Q01 # cross-user must DENY
```

Budget ceiling for canary: ≤ $0.25 after Research approval.
