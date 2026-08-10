from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from poc_runtime.clock import FixedClock, SystemClock
from poc_runtime.cost_guard import CostGuard
from poc_runtime.gates import GateRefusal, load_gemini_config, validate_gemini_invocation_gates
from poc_runtime.llm.fake import FakeLLMClient
from poc_runtime.llm.gemini import GeminiLLMClient
from poc_runtime.llm.types import EphemeralConversationContext
from poc_runtime.models import ExecutionTrace
from poc_runtime.orchestrator import ConversationOrchestrator
from poc_runtime.state_machine import TicketStateMachine
from poc_runtime.ticket_service import TicketService


class RunIsolationError(RuntimeError):
    pass


@dataclass
class ScenarioResult:
    scenario_id: str
    initial_ticket_ids: list[str]
    initial_state_sha256: str
    final_ticket_ids: list[str]
    final_state_sha256: str
    db_path: str
    seed_event_count: int = 0
    queries_run: int = 0


@dataclass
class B0RunSummary:
    run_id: str = ""
    split: str = "development"
    provider: str = "fake"
    purpose: str = "runtime_infrastructure_validation"
    quality_claim: bool = False
    scenarios_run: int = 0
    queries_run: int = 0
    traces_written: int = 0
    success_count: int = 0
    error_count: int = 0
    policy_allow: int = 0
    policy_deny: int = 0
    policy_clarify: int = 0
    policy_none: int = 0
    actions_proposed: int = 0
    actions_executed: int = 0
    missing_trace_count: int = 0
    initial_tickets_seeded: int = 0
    scenario_isolation_violations: int = 0
    cross_user_leakage: int = 0
    invalid_transition_executed: int = 0
    fake_fixture_coverage: int = 0
    expected_action_type_matches: int = 0
    expected_action_type_total: int = 0
    expected_action_type_accuracy: float = 0.0
    policy_decision_matches: int = 0
    action_type_counts: dict[str, int] = field(default_factory=dict)
    latency_ms_total: float = 0.0
    estimated_cost_usd: float = 0.0
    run_dir: str = ""
    traces_path: str = ""
    results_path: str = ""
    scenario_results_path: str = ""
    traces: list[ExecutionTrace] = field(default_factory=list)
    scenario_results: list[ScenarioResult] = field(default_factory=list)


def _load_scenarios(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data.get("scenarios") or [])


def _turns(scenario: dict) -> list[dict]:
    if scenario.get("turns"):
        return list(scenario["turns"])
    return list(scenario.get("queries") or [])


def _turn_text(turn: dict) -> str:
    return turn.get("user_message") or turn.get("text") or turn.get("query") or ""


def _ensure_fresh_run_dir(run_dir: Path) -> None:
    if run_dir.exists():
        # Refuse non-empty existing run directories (fail-closed, no overwrite).
        if any(run_dir.iterdir()):
            raise RunIsolationError(
                "REFUSED: run_id already exists; choose a new run_id"
            )
    run_dir.mkdir(parents=True, exist_ok=True)


def _refuse_existing_db(db_path: Path) -> None:
    if db_path.exists():
        raise RunIsolationError(
            f"REFUSED: db path already exists; choose a new path: {db_path}"
        )


def run_b0(
    *,
    project_root: Path,
    split: str = "development",
    provider: str = "fake",
    allow_eval: bool = False,
    run_id: str | None = None,
    db_path: Path | None = None,
    out_dir: Path | None = None,
    max_queries: int | None = None,
    fixture_path: Path | None = None,
    query_ids: list[str] | None = None,
    budget_usd: float | None = None,
    allow_paid: bool = False,
    confirm_live_call: str | None = None,
    preflight: bool = False,
    gemini_transport=None,
) -> B0RunSummary | dict[str, Any]:
    if split == "evaluation" and not allow_eval:
        raise SystemExit("evaluation split requires --allow-eval (read-only; never mutate)")
    if split == "evaluation" and provider == "gemini":
        raise GateRefusal("REFUSED: evaluation split with paid gemini provider is forbidden")

    if provider == "gemini":
        # Gate checks BEFORE creating any run directory / SQLite.
        report = validate_gemini_invocation_gates(
            project_root=project_root,
            split=split,
            provider=provider,
            allow_paid=allow_paid,
            confirm_live_call=confirm_live_call,
            query_ids=query_ids,
            budget_usd=budget_usd,
            preflight=preflight,
        )
        if preflight:
            return report

    if split == "development":
        scenarios_path = project_root / "data/scenarios/scenarios_dev.yaml"
        default_fixture = project_root / "tests/fixtures/b0/fake_actions_dev.yaml"
    elif split == "evaluation":
        scenarios_path = project_root / "data/scenarios/scenarios_eval.yaml"
        default_fixture = project_root / "tests/fixtures/b0/fake_actions_dev.yaml"
    else:
        raise SystemExit(f"unknown split: {split}")

    rid = run_id or f"b0-{split}-{uuid.uuid4().hex[:8]}"
    if out_dir is None:
        run_dir = project_root / "artifacts" / "b0_runs" / rid
    elif run_id is not None and out_dir.name != rid:
        run_dir = out_dir / rid
    else:
        run_dir = out_dir

    _ensure_fresh_run_dir(run_dir)
    if db_path is not None:
        raise RunIsolationError(
            "REFUSED: explicit shared --db is not supported in B0.1; "
            "use per-scenario DBs under --run-id"
        )

    traces_path = run_dir / "traces.jsonl"
    results_path = run_dir / "summary.json"
    scenario_results_path = run_dir / "scenario_results.json"
    ledger_path = run_dir / "cost_ledger.json"
    scenarios_root = run_dir / "scenarios"
    scenarios_root.mkdir(parents=True, exist_ok=True)

    sm = TicketStateMachine.from_policy_file(project_root)
    fx_path = fixture_path or default_fixture
    selected = set(query_ids) if query_ids else None

    # ONE run-scoped cost ledger shared by all scenario orchestrators.
    if provider == "fake":
        cost_guard = CostGuard.from_project(project_root, zero_cost=True)
        llm = FakeLLMClient(fixture_path=fx_path if fx_path.exists() else None)
        paid = False
        fixture_keys = set(llm.fixtures.keys())
    elif provider == "gemini":
        gcfg = load_gemini_config(project_root)
        cost_guard = CostGuard.from_project(
            project_root,
            hard_cap_usd=float(budget_usd if budget_usd is not None else gcfg.canary_budget_usd),
            zero_cost=False,
        )
        llm = GeminiLLMClient(
            model_id=gcfg.model_id,
            allow_paid=allow_paid,
            live_enabled=gcfg.live_enabled,
            timeout_seconds=gcfg.timeout_seconds,
            max_attempts=gcfg.max_attempts,
            cost_guard=cost_guard,
            transport=gemini_transport,
        )
        paid = True
        fixture_keys = set()
    else:
        raise SystemExit(f"unknown provider: {provider}")

    summary = B0RunSummary(
        run_id=rid,
        split=split,
        provider=provider,
        run_dir=str(run_dir),
        traces_path=str(traces_path),
        results_path=str(results_path),
        scenario_results_path=str(scenario_results_path),
    )
    scenarios = _load_scenarios(scenarios_path)
    query_count = 0
    action_counts: Counter[str] = Counter()
    seen_ticket_owners_by_scenario: dict[str, set[str]] = {}

    with traces_path.open("w", encoding="utf-8") as tf:
        for scenario in scenarios:
            if max_queries is not None and query_count >= max_queries:
                break
            if selected is not None:
                turn_ids = {str(t.get("query_id")) for t in _turns(scenario)}
                if turn_ids.isdisjoint(selected):
                    continue

            sid = str(scenario.get("scenario_id") or f"SCN-{query_count}")
            persona_id = scenario.get("persona_id") or scenario.get("user_id") or "synthetic-user"
            initial = scenario.get("initial_state") or {}
            clock_iso = initial.get("clock")
            clock = FixedClock(str(clock_iso)) if clock_iso else SystemClock()

            sc_dir = scenarios_root / sid
            sc_dir.mkdir(parents=True, exist_ok=True)
            sc_db = sc_dir / "tickets.sqlite"
            _refuse_existing_db(sc_db)

            tickets = TicketService(sc_db, state_machine=sm, clock=clock)
            seed_ids: list[str] = []
            for fixture in initial.get("ticket_store") or []:
                rec = tickets.seed_ticket(fixture)
                seed_ids.append(rec.ticket_id)
                summary.initial_tickets_seeded += 1
            seed_events = tickets.count_events(event_type="SEED")
            initial_sha = tickets.business_state_sha256()
            _ = initial.get("memory_store")

            # Fresh ephemeral conversation per scenario (not MAG Memory).
            conversation = EphemeralConversationContext()
            orch = ConversationOrchestrator(
                project_root=project_root,
                ticket_service=tickets,
                llm=llm,
                cost_guard=cost_guard,
                provider_is_paid=paid,
                state_machine=sm,
                run_id=rid,
                scenario_db_path=str(sc_db),
                initial_state_sha256=initial_sha,
                conversation=conversation,
            )

            sc_queries = 0
            for turn in _turns(scenario):
                if max_queries is not None and query_count >= max_queries:
                    break
                qid = str(turn.get("query_id") or f"Q-{query_count}")
                if selected is not None and qid not in selected:
                    continue
                query_count += 1
                sc_queries += 1
                text = _turn_text(turn)
                session = turn.get("session_id") or f"{sid}-{qid}"

                ctx: dict[str, Any] = {
                    "query_id": qid,
                    "scenario_id": sid,
                }

                if qid in fixture_keys:
                    summary.fake_fixture_coverage += 1

                trace = orch.handle_query(
                    trusted_user_id=str(persona_id),
                    user_message=text,
                    scenario_id=sid,
                    query_id=qid,
                    session_id=str(session),
                    context=ctx,
                )
                summary.traces.append(trace)
                tf.write(json.dumps(trace.model_dump(mode="json"), ensure_ascii=False) + "\n")
                summary.traces_written += 1
                summary.queries_run += 1
                summary.latency_ms_total += trace.latency_ms
                summary.estimated_cost_usd += trace.estimated_cost_usd

                if trace.error:
                    summary.error_count += 1
                else:
                    summary.success_count += 1

                if trace.proposed_action:
                    summary.actions_proposed += 1
                    at = trace.proposed_action.get("action_type") or "UNKNOWN"
                    action_counts[str(at)] += 1
                if trace.executed_action:
                    summary.actions_executed += 1

                pd = (trace.policy_decision or {}).get("decision")
                if pd == "ALLOW":
                    summary.policy_allow += 1
                elif pd == "DENY":
                    summary.policy_deny += 1
                elif pd == "CLARIFY":
                    summary.policy_clarify += 1
                elif pd == "NONE":
                    summary.policy_none += 1

                if (trace.policy_decision or {}).get("reason_code") == "TICKET_NOT_ACCESSIBLE":
                    answer = trace.answer or ""
                    foreign = None
                    for t in tickets.list_all_tickets():
                        if t.user_id != persona_id:
                            foreign = t
                            break
                    if foreign is not None:
                        if foreign.summary and foreign.summary in answer:
                            summary.cross_user_leakage += 1
                        if foreign.user_id in answer:
                            summary.cross_user_leakage += 1
                        if foreign.ticket_id in answer and "không thể" not in answer.lower():
                            summary.cross_user_leakage += 1

                gt = (turn.get("ground_truth") or {}).get("expected_action") or {}
                if gt.get("type"):
                    summary.expected_action_type_total += 1
                    proposed_type = (trace.proposed_action or {}).get("action_type")
                    if proposed_type == gt.get("type"):
                        summary.expected_action_type_matches += 1
                    expected_decision = gt.get("decision")
                    actual_decision = (trace.policy_decision or {}).get("decision")
                    if expected_decision and actual_decision == expected_decision:
                        summary.policy_decision_matches += 1

            if sc_queries == 0 and selected is not None:
                tickets.close()
                continue

            final_ids = [t.ticket_id for t in tickets.list_all_tickets()]
            final_sha = tickets.business_state_sha256()
            owners = {t.user_id for t in tickets.list_all_tickets()}
            seen_ticket_owners_by_scenario[sid] = owners

            summary.scenario_results.append(
                ScenarioResult(
                    scenario_id=sid,
                    initial_ticket_ids=seed_ids,
                    initial_state_sha256=initial_sha,
                    final_ticket_ids=final_ids,
                    final_state_sha256=final_sha,
                    db_path=str(sc_db),
                    seed_event_count=seed_events,
                    queries_run=sc_queries,
                )
            )
            summary.scenarios_run += 1
            tickets.close()

    summary.missing_trace_count = max(0, summary.queries_run - summary.traces_written)
    summary.action_type_counts = dict(action_counts)
    if summary.expected_action_type_total:
        summary.expected_action_type_accuracy = (
            summary.expected_action_type_matches / summary.expected_action_type_total
        )

    db_paths = [s.db_path for s in summary.scenario_results]
    if len(db_paths) != len(set(db_paths)):
        summary.scenario_isolation_violations += 1

    ledger = cost_guard.summary_dict()
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {
        "run_id": summary.run_id,
        "split": summary.split,
        "provider": summary.provider,
        "purpose": summary.purpose,
        "quality_claim": summary.quality_claim,
        "scenarios_run": summary.scenarios_run,
        "queries_run": summary.queries_run,
        "traces_written": summary.traces_written,
        "missing_trace": summary.missing_trace_count,
        "success_count": summary.success_count,
        "error_count": summary.error_count,
        "policy_allow": summary.policy_allow,
        "policy_deny": summary.policy_deny,
        "policy_clarify": summary.policy_clarify,
        "policy_none": summary.policy_none,
        "actions_proposed": summary.actions_proposed,
        "actions_executed": summary.actions_executed,
        "action_type_counts": summary.action_type_counts,
        "initial_tickets_seeded": summary.initial_tickets_seeded,
        "scenario_isolation_violations": summary.scenario_isolation_violations,
        "cross_user_leakage": summary.cross_user_leakage,
        "invalid_transition_executed": summary.invalid_transition_executed,
        "fake_fixture_coverage": summary.fake_fixture_coverage,
        "expected_action_type_matches": summary.expected_action_type_matches,
        "expected_action_type_total": summary.expected_action_type_total,
        "expected_action_type_accuracy": summary.expected_action_type_accuracy,
        "policy_decision_matches": summary.policy_decision_matches,
        "latency_ms_avg": (
            summary.latency_ms_total / summary.queries_run if summary.queries_run else 0.0
        ),
        "estimated_cost_usd": summary.estimated_cost_usd,
        "cumulative_run_cost_usd": cost_guard.cumulative_run_cost_usd,
        "cost_ledger": ledger,
        "run_dir": summary.run_dir,
        "traces_path": summary.traces_path,
        "memory_enabled": False,
    }
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    scenario_results_path.write_text(
        json.dumps([s.__dict__ for s in summary.scenario_results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
