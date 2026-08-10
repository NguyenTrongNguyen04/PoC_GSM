# Contributing

This is a **private** research repository. Do not publish forks or mirrors without project owner approval.

## Local workflow

1. Create a feature branch from `main`.
2. Keep changes scoped; do not mutate `scenarios_eval.yaml` or forge Research approvals.
3. Run offline validation before opening a PR:

```powershell
python -m pip install -r requirements-dev.txt
python scripts\validate_contracts.py
python scripts\validate_knowledge.py --scope offline-fixture --strict
python -m pytest tests -q
```

4. Never commit `.env`, API keys, SQLite run DBs, or handoff ZIPs.

## Safety rules

- No live Gemini unless Research enables gates and confirms budget.
- No corpus live fetch/publish in routine development.
- Ticket Store remains system of record; LLM must not gain a DB handle.
