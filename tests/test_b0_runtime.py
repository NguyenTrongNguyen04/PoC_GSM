"""Baseline B0 / B0.1 offline tests — no network, no Gemini, temporary SQLite only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from poc_runtime.cost_guard import CostGuard
from poc_runtime.db import init_db
from poc_runtime.errors import (
    ClosedTicketImmutable,
    InvalidTicketTransition,
    TicketAccessDenied,
    TicketError,
)
from poc_runtime.llm.fake import FakeLLMClient
from poc_runtime.llm.errors import ProviderError
from poc_runtime.llm.gemini import GeminiLLMClient
from poc_runtime.models import (
    ActionType,
    PolicyDecisionCode,
    StructuredAction,
    TicketLookupCode,
    TicketLookupOutcome,
    TicketStatus,
)
from poc_runtime.orchestrator import ConversationOrchestrator
from poc_runtime.policy import PolicyEngine
from poc_runtime.runner import RunIsolationError, run_b0
from poc_runtime.state_machine import TicketStateMachine
from poc_runtime.ticket_service import TicketService

ROOT = Path(__file__).resolve().parents[1]
EVAL_SHA = "dad9348245d46327f980f0221589f8a99fc3d9781e4f03a99682057ab7924be6"
MANIFEST_SHA = "6b16a6297596fca798d46ac64175c270d3000a718165aa86ed81d6b15ce6c3cd"
STAGED_BUNDLE_SHA = "860996a1460a905664cd87521c31510a5a5dfc0e8a9b1f077fd50600723b71cf"
FIXTURE = ROOT / "tests/fixtures/b0/fake_actions_dev.yaml"


@pytest.fixture
def sm() -> TicketStateMachine:
    return TicketStateMachine.from_policy_file(ROOT)


@pytest.fixture
def tmp_tickets(tmp_path: Path, sm: TicketStateMachine) -> TicketService:
    return TicketService(tmp_path / "tickets.sqlite", state_machine=sm)


def test_sqlite_init_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    c1 = init_db(db)
    c1.execute(
        "INSERT INTO tickets(ticket_id,user_id,complaint_type,status,summary,created_at,updated_at) "
        "VALUES ('T1','U1','X','OPEN','','t','t')"
    )
    c1.commit()
    c1.close()
    c2 = init_db(db)
    row = c2.execute("SELECT ticket_id FROM tickets WHERE ticket_id='T1'").fetchone()
    assert row["ticket_id"] == "T1"
    c2.close()


def test_create_ticket_success(tmp_tickets: TicketService) -> None:
    t = tmp_tickets.create_ticket(
        trusted_user_id="U1", complaint_type="CANCELLED_TRIP_CHARGE", summary="test"
    )
    assert t.status == TicketStatus.OPEN
    assert t.user_id == "U1"
    assert t.version == 1


def test_cross_user_read_update_denied(tmp_tickets: TicketService) -> None:
    t = tmp_tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    with pytest.raises(TicketAccessDenied):
        tmp_tickets.get_ticket(trusted_user_id="U2", ticket_id=t.ticket_id)
    with pytest.raises(TicketAccessDenied):
        tmp_tickets.update_ticket(trusted_user_id="U2", ticket_id=t.ticket_id, summary="nope")


def test_invalid_state_transition_denied_policy(tmp_tickets: TicketService, sm: TicketStateMachine) -> None:
    policy = PolicyEngine(ROOT, state_machine=sm)
    t = tmp_tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    action = StructuredAction(
        action_type=ActionType.UPDATE_TICKET,
        user_id="U1",
        ticket_id=t.ticket_id,
        requested_transition=TicketStatus.CLOSED,
        reason="illegal hop",
    )
    lookup = TicketLookupOutcome(code=TicketLookupCode.FOUND, ticket=t)
    result = policy.validate(trusted_user_id="U1", action=action, lookup=lookup)
    assert result.decision == PolicyDecisionCode.DENY
    assert result.reason_code == "INVALID_TRANSITION"


def test_closed_ticket_immutable(tmp_tickets: TicketService) -> None:
    t = tmp_tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    tmp_tickets.transition_ticket(
        trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.IN_REVIEW
    )
    tmp_tickets.transition_ticket(
        trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.RESOLVED
    )
    closed = tmp_tickets.close_ticket(trusted_user_id="U1", ticket_id=t.ticket_id)
    assert closed.status == TicketStatus.CLOSED
    with pytest.raises(ClosedTicketImmutable):
        tmp_tickets.update_ticket(trusted_user_id="U1", ticket_id=t.ticket_id, summary="x")


def test_llm_cannot_write_db_directly(tmp_tickets: TicketService) -> None:
    llm = FakeLLMClient()
    assert not hasattr(llm, "conn")
    assert not hasattr(llm, "create_ticket")
    before = tmp_tickets.list_user_tickets(trusted_user_id="U1")
    llm.propose_action(trusted_user_id="U1", user_message="tạo ticket khiếu nại")
    after = tmp_tickets.list_user_tickets(trusted_user_id="U1")
    assert before == after


def test_invalid_structured_action_fail_closed(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "bad": StructuredAction(
                    action_type=ActionType.CREATE_TICKET,
                    user_id="ATTACKER",
                    complaint_type="X",
                    reason="spoof",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U1",
        user_message="x",
        query_id="bad",
        context={"query_id": "bad"},
    )
    assert trace.policy_decision["decision"] == "DENY"
    assert tickets.list_user_tickets(trusted_user_id="U1") == []
    assert tickets.list_user_tickets(trusted_user_id="ATTACKER") == []


def test_missing_required_fields_clarify(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "miss": StructuredAction(
                    action_type=ActionType.CREATE_TICKET,
                    user_id="U1",
                    complaint_type=None,
                    reason="missing type",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U1",
        user_message="x",
        query_id="miss",
        context={"query_id": "miss"},
    )
    assert trace.policy_decision["decision"] == "CLARIFY"
    assert tickets.list_user_tickets(trusted_user_id="U1") == []


def test_fake_llm_deterministic() -> None:
    llm = FakeLLMClient(fixture_path=FIXTURE)
    a1 = llm.propose_action(
        trusted_user_id="U1", user_message="x", context={"query_id": "P-DEV-02-Q01"}
    )
    a2 = llm.propose_action(
        trusted_user_id="U1", user_message="x", context={"query_id": "P-DEV-02-Q01"}
    )
    assert a1.action.model_dump() == a2.action.model_dump()
    assert a1.actual_cost_usd == 0.0


def test_refund_policy_gate(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "refund": StructuredAction(
                    action_type=ActionType.NONE,
                    user_id="U1",
                    reason="ok",
                    answer_text="Tôi cam kết hoàn tiền ngay hôm nay",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U1",
        user_message="x",
        query_id="refund",
        context={"query_id": "refund"},
    )
    assert trace.policy_decision["decision"] == "DENY"
    assert trace.policy_decision["reason_code"] == "REFUND_OR_COMPENSATION_COMMITMENT"
    assert trace.error is None


def test_one_query_one_trace(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT, ticket_service=tickets, llm=FakeLLMClient(), state_machine=sm
    )
    trace = orch.handle_query(trusted_user_id="U1", user_message="xin chào")
    assert trace.baseline == "B0"
    assert trace.trusted_user_id == "U1"
    assert trace.timestamp
    assert trace.error is None


def test_llm_error_still_has_trace(tmp_path: Path, sm: TicketStateMachine) -> None:
    class Boom(FakeLLMClient):
        def propose_action(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("llm exploded")

    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT, ticket_service=tickets, llm=Boom(), state_machine=sm
    )
    trace = orch.handle_query(trusted_user_id="U1", user_message="x")
    assert trace.error is not None
    assert "llm exploded" in trace.error
    assert trace.timestamp


def test_cost_guard_blocks_over_budget() -> None:
    guard = CostGuard(hard_cap_usd=0.0001, input_per_1m=10.0, output_per_1m=10.0)
    est = guard.estimate(input_tokens=100_000, output_tokens=100_000)
    with pytest.raises(ProviderError, match="cost guard reject"):
        guard.authorize(est)


def test_fake_provider_zero_cost(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(fixture_path=FIXTURE),
        cost_guard=CostGuard(),
        provider_is_paid=False,
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U1",
        user_message="x",
        query_id="P-DEV-02-Q01",
        context={"query_id": "P-DEV-02-Q01"},
    )
    assert trace.estimated_cost_usd == 0.0


def test_development_smoke_runner_reproducible(tmp_path: Path) -> None:
    s1 = run_b0(
        project_root=ROOT,
        split="development",
        provider="fake",
        run_id="unit-r1",
        out_dir=tmp_path,
        max_queries=5,
        fixture_path=FIXTURE,
    )
    s2 = run_b0(
        project_root=ROOT,
        split="development",
        provider="fake",
        run_id="unit-r2",
        out_dir=tmp_path,
        max_queries=5,
        fixture_path=FIXTURE,
    )
    assert s1.queries_run == s2.queries_run == 5
    assert s1.missing_trace_count == 0
    assert s1.estimated_cost_usd == 0.0
    assert [t.proposed_action for t in s1.traces] == [t.proposed_action for t in s2.traces]
    assert [r.final_state_sha256 for r in s1.scenario_results] == [
        r.final_state_sha256 for r in s2.scenario_results
    ]


def test_eval_sha_unchanged() -> None:
    digest = hashlib.sha256((ROOT / "data/scenarios/scenarios_eval.yaml").read_bytes()).hexdigest()
    assert digest == EVAL_SHA


def test_unit_tests_need_no_network_or_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiLLMClient(allow_paid=False, live_enabled=False)
    with pytest.raises(ProviderError, match="live gate closed"):
        client.propose_action(trusted_user_id="U1", user_message="hi")


# ---- B0.1 acceptance additions ----


def test_valid_transitions_succeed(tmp_tickets: TicketService) -> None:
    t = tmp_tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    t = tmp_tickets.transition_ticket(
        trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.WAITING_CUSTOMER
    )
    assert t.status == TicketStatus.WAITING_CUSTOMER
    t = tmp_tickets.transition_ticket(
        trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.IN_REVIEW
    )
    assert t.status == TicketStatus.IN_REVIEW
    t = tmp_tickets.transition_ticket(
        trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.RESOLVED
    )
    assert t.status == TicketStatus.RESOLVED
    t = tmp_tickets.transition_ticket(
        trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.CLOSED
    )
    assert t.status == TicketStatus.CLOSED


def test_open_to_closed_blocked_at_service(tmp_tickets: TicketService) -> None:
    t = tmp_tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    version_before = t.version
    events_before = tmp_tickets.count_events(event_type="TRANSITION")
    with pytest.raises(InvalidTicketTransition):
        tmp_tickets.transition_ticket(
            trusted_user_id="U1", ticket_id=t.ticket_id, to_status=TicketStatus.CLOSED
        )
    after = tmp_tickets.get_ticket(trusted_user_id="U1", ticket_id=t.ticket_id)
    assert after.status == TicketStatus.OPEN
    assert after.version == version_before
    assert tmp_tickets.count_events(event_type="TRANSITION") == events_before


def test_all_invalid_transitions_blocked_service(tmp_tickets: TicketService, sm: TicketStateMachine) -> None:
    t = tmp_tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    for status in TicketStatus:
        if not sm.can_transition(TicketStatus.OPEN, status):
            with pytest.raises(InvalidTicketTransition):
                tmp_tickets.transition_ticket(
                    trusted_user_id="U1", ticket_id=t.ticket_id, to_status=status
                )


def test_cross_user_update_policy_deny_no_service_mutation(
    tmp_path: Path, sm: TicketStateMachine
) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    owner_t = tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    # Seed foreign view via raw create under U1; U2 proposes update
    calls: list[str] = []
    orig = tickets.update_ticket

    def wrapped(**kwargs):  # type: ignore[no-untyped-def]
        calls.append("update")
        return orig(**kwargs)

    tickets.update_ticket = wrapped  # type: ignore[method-assign]
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "x": StructuredAction(
                    action_type=ActionType.UPDATE_TICKET,
                    user_id="U2",
                    ticket_id=owner_t.ticket_id,
                    fields={"summary": "hack"},
                    reason="cross",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U2", user_message="x", query_id="x", context={"query_id": "x"}
    )
    assert trace.policy_decision["decision"] == "DENY"
    assert trace.policy_reason_code == "TICKET_NOT_ACCESSIBLE"
    assert trace.executed_action is None
    assert trace.error is None
    assert calls == []
    assert "U1" not in trace.answer
    if owner_t.summary:
        assert owner_t.summary not in (trace.answer or "")
    assert owner_t.ticket_id not in (trace.answer or "")


def test_cross_user_close_policy_deny(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    t = tickets.create_ticket(trusted_user_id="U1", complaint_type="X")
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "c": StructuredAction(
                    action_type=ActionType.CLOSE_TICKET,
                    user_id="U2",
                    ticket_id=t.ticket_id,
                    reason="cross close",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U2", user_message="x", query_id="c", context={"query_id": "c"}
    )
    assert trace.policy_decision["decision"] == "DENY"
    assert trace.executed_action is None


def test_unknown_ticket_not_allow(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "u": StructuredAction(
                    action_type=ActionType.GET_TICKET_STATUS,
                    user_id="U1",
                    ticket_id="TCK-DOES-NOT-EXIST",
                    reason="missing",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U1", user_message="x", query_id="u", context={"query_id": "u"}
    )
    assert trace.policy_decision["decision"] != "ALLOW"
    assert trace.policy_reason_code == "TICKET_NOT_FOUND_OR_UNAVAILABLE"


def test_missing_ticket_id_clarify(tmp_path: Path, sm: TicketStateMachine) -> None:
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=FakeLLMClient(
            fixtures={
                "m": StructuredAction(
                    action_type=ActionType.GET_TICKET_STATUS,
                    user_id="U1",
                    ticket_id=None,
                    reason="no id",
                )
            }
        ),
        state_machine=sm,
    )
    trace = orch.handle_query(
        trusted_user_id="U1", user_message="x", query_id="m", context={"query_id": "m"}
    )
    assert trace.policy_decision["decision"] == "CLARIFY"
    assert trace.policy_reason_code == "MISSING_TICKET_ID"


def test_scenario_isolation_and_seed(tmp_path: Path) -> None:
    summary = run_b0(
        project_root=ROOT,
        split="development",
        provider="fake",
        run_id="iso-1",
        out_dir=tmp_path,
        fixture_path=FIXTURE,
    )
    assert summary.initial_tickets_seeded == 5
    assert summary.scenarios_run == 12
    assert summary.queries_run == 30
    assert summary.traces_written == 30
    assert summary.missing_trace_count == 0
    assert summary.fake_fixture_coverage == 30
    assert summary.scenario_isolation_violations == 0
    assert summary.cross_user_leakage == 0
    assert summary.estimated_cost_usd == 0.0

    dbs = [Path(s.db_path) for s in summary.scenario_results]
    assert len(dbs) == len(set(dbs))
    # Same persona scenarios must not share tickets across DBs
    s_dev_01 = next(s for s in summary.scenario_results if s.scenario_id == "S-DEV-01")
    h_dev_01 = next(s for s in summary.scenario_results if s.scenario_id == "H-DEV-01")
    assert "TCK-DEV-101" in s_dev_01.initial_ticket_ids
    assert "TCK-DEV-301" in h_dev_01.initial_ticket_ids
    assert "TCK-DEV-101" not in h_dev_01.final_ticket_ids
    assert "TCK-DEV-301" not in s_dev_01.final_ticket_ids

    sec = next(s for s in summary.scenario_results if s.scenario_id == "SEC-DEV-01")
    assert "TCK-DEV-OTHER-01" in sec.initial_ticket_ids
    assert sec.seed_event_count == 1
    # SEED must not appear as executed LLM action
    sec_traces = [t for t in summary.traces if t.scenario_id == "SEC-DEV-01"]
    for tr in sec_traces:
        if tr.executed_action:
            assert tr.executed_action.get("action_type") != "SEED"


def test_run_id_refuse_existing(tmp_path: Path) -> None:
    run_b0(
        project_root=ROOT,
        split="development",
        provider="fake",
        run_id="dup",
        out_dir=tmp_path,
        max_queries=1,
        fixture_path=FIXTURE,
    )
    with pytest.raises(RunIsolationError, match="run_id already exists"):
        run_b0(
            project_root=ROOT,
            split="development",
            provider="fake",
            run_id="dup",
            out_dir=tmp_path,
            max_queries=1,
            fixture_path=FIXTURE,
        )


def test_shared_db_path_refused(tmp_path: Path) -> None:
    with pytest.raises(RunIsolationError, match="explicit shared --db"):
        run_b0(
            project_root=ROOT,
            split="development",
            provider="fake",
            run_id="dbref",
            out_dir=tmp_path,
            db_path=tmp_path / "shared.sqlite",
            max_queries=1,
            fixture_path=FIXTURE,
        )


def test_hashes_unchanged() -> None:
    assert (
        hashlib.sha256((ROOT / "data/scenarios/scenarios_eval.yaml").read_bytes()).hexdigest()
        == EVAL_SHA
    )
    assert (
        hashlib.sha256((ROOT / "data/corpus/corpus_manifest.csv").read_bytes()).hexdigest()
        == MANIFEST_SHA
    )
    import json

    prov = json.loads((ROOT / "artifacts/live_staging/bundle_provenance.json").read_text(encoding="utf-8"))
    assert prov["staged_bundle_sha256"] == STAGED_BUNDLE_SHA


def test_no_silent_ticketerror_pass() -> None:
    text = (ROOT / "src/poc_runtime/orchestrator.py").read_text(encoding="utf-8")
    assert "except TicketError" not in text
    assert "except TicketError:\n            pass" not in text
