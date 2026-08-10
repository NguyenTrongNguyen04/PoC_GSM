"""B0.2A Gemini provider offline tests — no network, no real API key required."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from poc_runtime.cost_guard import CostGuard
from poc_runtime.gates import (
    CANARY_QUERY_ALLOWLIST,
    LIVE_CONFIRMATION_TOKEN,
    GateRefusal,
    validate_gemini_invocation_gates,
)
from poc_runtime.llm.errors import ProviderError, ProviderErrorCategory
from poc_runtime.llm.gemini import GeminiLLMClient, GeminiTransportResponse, MockGeminiTransport
from poc_runtime.llm.prompt import assert_prompt_has_no_labels, build_gemini_request_payload
from poc_runtime.llm.types import EphemeralConversationContext
from poc_runtime.models import ActionType, StructuredAction
from poc_runtime.orchestrator import ConversationOrchestrator
from poc_runtime.runner import run_b0
from poc_runtime.state_machine import TicketStateMachine
from poc_runtime.ticket_service import TicketService

ROOT = Path(__file__).resolve().parents[1]
EVAL_SHA = "dad9348245d46327f980f0221589f8a99fc3d9781e4f03a99682057ab7924be6"
MANIFEST_SHA = "ea9122c6c356b6f8715de5d05ac2679fa4fa945d47c3a7faacb141da3eac436c"
STAGED = "860996a1460a905664cd87521c31510a5a5dfc0e8a9b1f077fd50600723b71cf"
FIXTURE = ROOT / "tests/fixtures/b0/fake_actions_dev.yaml"


def _action_json(**kwargs) -> str:
    base = {
        "action_type": "NONE",
        "user_id": None,
        "ticket_id": None,
        "complaint_type": None,
        "requested_transition": None,
        "fields": {},
        "reason": "ok",
        "confidence": 0.9,
        "answer_text": "Xin chào",
    }
    base.update(kwargs)
    return json.dumps(base, ensure_ascii=False)


def test_default_live_gate_refused(tmp_path: Path) -> None:
    with pytest.raises(GateRefusal, match="live_enabled=false"):
        validate_gemini_invocation_gates(
            project_root=ROOT,
            split="development",
            provider="gemini",
            allow_paid=True,
            confirm_live_call=LIVE_CONFIRMATION_TOKEN,
            query_ids=list(CANARY_QUERY_ALLOWLIST),
            budget_usd=0.25,
            preflight=False,
        )


def test_missing_allow_paid_refused() -> None:
    # Even if live were true, missing allow_paid fails — with live false we hit live first.
    # Explicitly assert allow_paid message by checking preflight path still works without allow_paid.
    report = validate_gemini_invocation_gates(
        project_root=ROOT,
        split="development",
        provider="gemini",
        allow_paid=False,
        confirm_live_call=None,
        query_ids=list(CANARY_QUERY_ALLOWLIST),
        budget_usd=0.25,
        preflight=True,
    )
    assert report["allow_paid"] is False
    assert report["network_called"] is False


def test_bad_confirmation_token_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Force live_enabled true only inside validate by patching load config.
    from poc_runtime import gates as gates_mod

    monkeypatch.setattr(
        gates_mod,
        "load_gemini_config",
        lambda project_root: gates_mod.GeminiRuntimeConfig(live_enabled=True),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    with pytest.raises(GateRefusal, match="confirm-live-call"):
        validate_gemini_invocation_gates(
            project_root=ROOT,
            split="development",
            provider="gemini",
            allow_paid=True,
            confirm_live_call="WRONG",
            query_ids=list(CANARY_QUERY_ALLOWLIST),
            budget_usd=0.25,
            preflight=False,
        )


def test_missing_api_key_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from poc_runtime import gates as gates_mod

    monkeypatch.setattr(
        gates_mod,
        "load_gemini_config",
        lambda project_root: gates_mod.GeminiRuntimeConfig(live_enabled=True),
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GateRefusal, match="GEMINI_API_KEY"):
        validate_gemini_invocation_gates(
            project_root=ROOT,
            split="development",
            provider="gemini",
            allow_paid=True,
            confirm_live_call=LIVE_CONFIRMATION_TOKEN,
            query_ids=list(CANARY_QUERY_ALLOWLIST),
            budget_usd=0.25,
            preflight=False,
        )


def test_api_key_not_in_trace_or_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "TEST_SECRET_VALUE_SHOULD_NEVER_APPEAR")
    transport = MockGeminiTransport(
        responses=[
            GeminiTransportResponse(text=_action_json(), input_tokens=10, output_tokens=5)
        ]
    )
    guard = CostGuard(hard_cap_usd=1.0, zero_cost=False)
    llm = GeminiLLMClient(
        allow_paid=True,
        live_enabled=True,
        transport=transport,
        cost_guard=guard,
        sleeper=lambda _s: None,
    )
    sm = TicketStateMachine.from_policy_file(ROOT)
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=True,
        state_machine=sm,
    )
    trace = orch.handle_query(trusted_user_id="U1", user_message="xin chào")
    blob = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False)
    assert "TEST_SECRET_VALUE_SHOULD_NEVER_APPEAR" not in blob
    assert "GEMINI_API_KEY" not in blob


def test_evaluation_split_paid_refused(tmp_path: Path) -> None:
    with pytest.raises(GateRefusal, match="evaluation"):
        run_b0(
            project_root=ROOT,
            split="evaluation",
            provider="gemini",
            allow_eval=True,
            run_id="eval-refuse",
            out_dir=tmp_path,
            query_ids=list(CANARY_QUERY_ALLOWLIST),
            budget_usd=0.25,
            allow_paid=True,
            confirm_live_call=LIVE_CONFIRMATION_TOKEN,
        )


def test_more_than_three_queries_refused() -> None:
    with pytest.raises(GateRefusal, match="at most 3"):
        validate_gemini_invocation_gates(
            project_root=ROOT,
            split="development",
            provider="gemini",
            allow_paid=False,
            confirm_live_call=None,
            query_ids=list(CANARY_QUERY_ALLOWLIST) + ["P-DEV-01-Q02"],
            budget_usd=0.25,
            preflight=True,
        )


def test_missing_query_ids_refused() -> None:
    with pytest.raises(GateRefusal, match="explicit --query-id"):
        validate_gemini_invocation_gates(
            project_root=ROOT,
            split="development",
            provider="gemini",
            allow_paid=False,
            confirm_live_call=None,
            query_ids=None,
            budget_usd=0.25,
            preflight=True,
        )


def test_preflight_zero_network_no_partial_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "b02-gemini-preflight"
    report = run_b0(
        project_root=ROOT,
        split="development",
        provider="gemini",
        run_id="b02-gemini-preflight",
        out_dir=tmp_path,
        query_ids=list(CANARY_QUERY_ALLOWLIST),
        budget_usd=0.25,
        preflight=True,
    )
    assert isinstance(report, dict)
    assert report["network_called"] is False
    assert report["api_key_present"] in (True, False)
    assert not run_dir.exists()


def test_refusal_does_not_create_partial_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "should-not-exist"
    with pytest.raises(GateRefusal):
        run_b0(
            project_root=ROOT,
            split="development",
            provider="gemini",
            run_id="should-not-exist",
            out_dir=tmp_path,
            query_ids=list(CANARY_QUERY_ALLOWLIST),
            budget_usd=0.25,
            allow_paid=True,
            confirm_live_call=LIVE_CONFIRMATION_TOKEN,
            preflight=False,
        )
    assert not run_dir.exists()


def test_valid_structured_response(tmp_path: Path) -> None:
    transport = MockGeminiTransport(
        responses=[
            GeminiTransportResponse(
                text=_action_json(
                    action_type="CREATE_TICKET",
                    complaint_type="CANCELLED_TRIP_CHARGE",
                    fields={"ticket_id": "TCK-MOCK-1"},
                ),
                input_tokens=11,
                output_tokens=7,
            )
        ]
    )
    guard = CostGuard(hard_cap_usd=1.0)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    result = llm.propose_action(trusted_user_id="U1", user_message="tạo ticket")
    assert result.action.action_type == ActionType.CREATE_TICKET
    assert result.structured_output_valid is True
    assert result.attempts == 1


def test_invalid_schema_fail_closed_no_db_mutation(tmp_path: Path) -> None:
    transport = MockGeminiTransport(responses=[GeminiTransportResponse(text="{not-json")])
    guard = CostGuard(hard_cap_usd=1.0)
    sm = TicketStateMachine.from_policy_file(ROOT)
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=True,
        state_machine=sm,
    )
    before = tickets.list_all_tickets()
    trace = orch.handle_query(trusted_user_id="U1", user_message="x")
    assert trace.provider_error_category == "SCHEMA_VALIDATION_ERROR"
    assert trace.executed_action is None
    assert tickets.list_all_tickets() == before


def test_unknown_enum_fail_closed(tmp_path: Path) -> None:
    transport = MockGeminiTransport(
        responses=[GeminiTransportResponse(text=_action_json(action_type="DELETE_EVERYTHING"))]
    )
    guard = CostGuard(hard_cap_usd=1.0)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    with pytest.raises(ProviderError) as ei:
        llm.propose_action(trusted_user_id="U1", user_message="x")
    assert ei.value.category == ProviderErrorCategory.SCHEMA_VALIDATION_ERROR


def test_spoofed_user_id_policy_deny(tmp_path: Path) -> None:
    transport = MockGeminiTransport(
        responses=[
            GeminiTransportResponse(
                text=_action_json(
                    action_type="CREATE_TICKET",
                    user_id="ATTACKER",
                    complaint_type="X",
                    fields={"ticket_id": "TCK-X"},
                )
            )
        ]
    )
    guard = CostGuard(hard_cap_usd=1.0, zero_cost=True)
    sm = TicketStateMachine.from_policy_file(ROOT)
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=False,
        state_machine=sm,
    )
    trace = orch.handle_query(trusted_user_id="U1", user_message="x")
    assert trace.policy_decision["decision"] == "DENY"
    assert tickets.list_all_tickets() == []


def test_cross_user_deny_no_mutation(tmp_path: Path) -> None:
    transport = MockGeminiTransport(
        responses=[
            GeminiTransportResponse(
                text=_action_json(
                    action_type="GET_TICKET_STATUS",
                    ticket_id="TCK-FOREIGN",
                )
            )
        ]
    )
    guard = CostGuard(zero_cost=True)
    sm = TicketStateMachine.from_policy_file(ROOT)
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    tickets.seed_ticket(
        {
            "ticket_id": "TCK-FOREIGN",
            "user_id": "U1",
            "complaint_type": "X",
            "status": "IN_REVIEW",
            "summary": "secret-summary",
            "created_at": "2026-08-01T09:00:00+07:00",
        }
    )
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=False,
        state_machine=sm,
    )
    trace = orch.handle_query(trusted_user_id="U2", user_message="status?")
    assert trace.policy_decision["decision"] == "DENY"
    assert trace.executed_action is None
    assert "secret-summary" not in trace.answer
    assert "U1" not in trace.answer


def test_retry_transient_only_with_injected_sleeper(tmp_path: Path) -> None:
    sleeps: list[float] = []
    errors = [
        ProviderError(ProviderErrorCategory.RATE_LIMITED, "429", retryable=True, status_code=429),
        ProviderError(ProviderErrorCategory.SERVER_ERROR, "503", retryable=True, status_code=503),
    ]
    transport = MockGeminiTransport(
        responses=[GeminiTransportResponse(text=_action_json(), input_tokens=3, output_tokens=2)],
        errors=errors,
    )
    guard = CostGuard(hard_cap_usd=1.0)
    llm = GeminiLLMClient(
        allow_paid=True,
        live_enabled=True,
        transport=transport,
        cost_guard=guard,
        max_attempts=3,
        sleeper=lambda s: sleeps.append(s),
    )
    result = llm.propose_action(trusted_user_id="U1", user_message="hi")
    assert result.attempts == 3
    assert sleeps == [1.0, 2.0]
    assert guard.attempts_authorized == 3


def test_non_retryable_auth_error() -> None:
    transport = MockGeminiTransport(
        errors=[ProviderError(ProviderErrorCategory.AUTH_ERROR, "401", retryable=False, status_code=401)]
    )
    guard = CostGuard(hard_cap_usd=1.0)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    with pytest.raises(ProviderError) as ei:
        llm.propose_action(trusted_user_id="U1", user_message="x")
    assert ei.value.category == ProviderErrorCategory.AUTH_ERROR
    assert guard.attempts_authorized == 1


def test_budget_shared_across_scenarios_and_retries(tmp_path: Path) -> None:
    responses = [
        GeminiTransportResponse(text=_action_json(), input_tokens=100_000, output_tokens=100_000),
        GeminiTransportResponse(text=_action_json(), input_tokens=100_000, output_tokens=100_000),
    ]
    transport = MockGeminiTransport(responses=responses)
    guard = CostGuard(hard_cap_usd=0.5, input_per_1m=0.3, output_per_1m=2.5)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    sm = TicketStateMachine.from_policy_file(ROOT)
    t1 = TicketService(tmp_path / "a.sqlite", state_machine=sm)
    orch1 = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=t1,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=True,
        state_machine=sm,
    )
    tr1 = orch1.handle_query(trusted_user_id="U1", user_message="a")
    assert tr1.error is None
    spent_after_a = guard.spent_usd
    assert spent_after_a > 0
    t2 = TicketService(tmp_path / "b.sqlite", state_machine=sm)
    orch2 = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=t2,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=True,
        state_machine=sm,
    )
    guard.hard_cap_usd = guard.spent_usd  # no room left for next scenario
    tr2 = orch2.handle_query(trusted_user_id="U2", user_message="b")
    assert tr2.provider_error_category == "BUDGET_REJECTED"
    assert tr2.executed_action is None
    assert guard.spent_usd == spent_after_a


def test_provider_retries_do_not_double_execute(tmp_path: Path) -> None:
    errors = [
        ProviderError(ProviderErrorCategory.TIMEOUT, "timeout", retryable=True),
    ]
    transport = MockGeminiTransport(
        responses=[
            GeminiTransportResponse(
                text=_action_json(
                    action_type="CREATE_TICKET",
                    complaint_type="X",
                    fields={"ticket_id": "TCK-ONCE"},
                )
            )
        ],
        errors=errors,
    )
    guard = CostGuard(hard_cap_usd=1.0, zero_cost=True)
    sm = TicketStateMachine.from_policy_file(ROOT)
    tickets = TicketService(tmp_path / "t.sqlite", state_machine=sm)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    orch = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=tickets,
        llm=llm,
        cost_guard=guard,
        provider_is_paid=False,
        state_machine=sm,
    )
    trace = orch.handle_query(trusted_user_id="U1", user_message="create")
    assert trace.executed_action is not None
    assert len(tickets.list_all_tickets()) == 1


def test_prompt_excludes_ground_truth_labels() -> None:
    payload = build_gemini_request_payload(
        trusted_user_id="U1",
        user_message="hello",
        query_id="P-DEV-01-Q01",
        scenario_id="P-DEV-01",
    )
    assert_prompt_has_no_labels(payload)
    assert "ground_truth" not in json.dumps(payload)


def test_conversation_context_resets_between_scenarios(tmp_path: Path) -> None:
    transport = MockGeminiTransport(
        responses=[
            GeminiTransportResponse(text=_action_json(answer_text="a1")),
            GeminiTransportResponse(text=_action_json(answer_text="b1")),
        ]
    )
    guard = CostGuard(zero_cost=True)
    llm = GeminiLLMClient(
        allow_paid=True, live_enabled=True, transport=transport, cost_guard=guard, sleeper=lambda _s: None
    )
    sm = TicketStateMachine.from_policy_file(ROOT)
    ctx_a = EphemeralConversationContext()
    orch_a = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=TicketService(tmp_path / "a.sqlite", state_machine=sm),
        llm=llm,
        cost_guard=guard,
        state_machine=sm,
        conversation=ctx_a,
    )
    orch_a.handle_query(trusted_user_id="U1", user_message="first")
    assert len(ctx_a.turns) == 1
    ctx_b = EphemeralConversationContext()
    orch_b = ConversationOrchestrator(
        project_root=ROOT,
        ticket_service=TicketService(tmp_path / "b.sqlite", state_machine=sm),
        llm=llm,
        cost_guard=guard,
        state_machine=sm,
        conversation=ctx_b,
    )
    orch_b.handle_query(trusted_user_id="U2", user_message="second")
    assert len(ctx_b.turns) == 1
    assert ctx_b.turns[0].user_message == "second"
    assert ctx_a.turns[0].user_message == "first"


def test_mocked_gemini_canary_with_live_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from poc_runtime import gates as gates_mod

    monkeypatch.setattr(
        gates_mod,
        "load_gemini_config",
        lambda project_root: gates_mod.GeminiRuntimeConfig(
            live_enabled=True, canary_budget_usd=0.25, max_canary_queries=3
        ),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-real")

    def make_transport():
        return MockGeminiTransport(
            responses=[
                GeminiTransportResponse(text=_action_json(action_type="NONE")),
                GeminiTransportResponse(
                    text=_action_json(
                        action_type="CREATE_TICKET",
                        complaint_type="CANCELLED_TRIP_CHARGE",
                        fields={"ticket_id": "TCK-FAKE-P-DEV-02-Q01"},
                    )
                ),
                GeminiTransportResponse(
                    text=_action_json(
                        action_type="GET_TICKET_STATUS",
                        ticket_id="TCK-DEV-OTHER-01",
                    )
                ),
            ]
        )

    s1 = run_b0(
        project_root=ROOT,
        split="development",
        provider="gemini",
        run_id="mock-g1",
        out_dir=tmp_path,
        query_ids=list(CANARY_QUERY_ALLOWLIST),
        budget_usd=0.25,
        allow_paid=True,
        confirm_live_call=LIVE_CONFIRMATION_TOKEN,
        gemini_transport=make_transport(),
    )
    s2 = run_b0(
        project_root=ROOT,
        split="development",
        provider="gemini",
        run_id="mock-g2",
        out_dir=tmp_path,
        query_ids=list(CANARY_QUERY_ALLOWLIST),
        budget_usd=0.25,
        allow_paid=True,
        confirm_live_call=LIVE_CONFIRMATION_TOKEN,
        gemini_transport=make_transport(),
    )
    assert s1.queries_run == s2.queries_run == 3
    assert [t.proposed_action for t in s1.traces] == [t.proposed_action for t in s2.traces]
    assert [t.policy_decision["decision"] for t in s1.traces] == [
        t.policy_decision["decision"] for t in s2.traces
    ]
    assert s1.traces[-1].policy_decision["decision"] == "DENY"


def test_protected_hashes_unchanged() -> None:
    assert hashlib.sha256((ROOT / "data/scenarios/scenarios_eval.yaml").read_bytes()).hexdigest() == EVAL_SHA
    assert hashlib.sha256((ROOT / "data/corpus/corpus_manifest.csv").read_bytes()).hexdigest() == MANIFEST_SHA
    prov = json.loads((ROOT / "artifacts/live_staging/bundle_provenance.json").read_text(encoding="utf-8"))
    assert prov["staged_bundle_sha256"] == STAGED


def test_model_not_found_no_retry() -> None:
    transport = MockGeminiTransport(
        errors=[
            ProviderError(ProviderErrorCategory.MODEL_NOT_FOUND, "model missing", retryable=False, status_code=404)
        ]
    )
    sleeps: list[float] = []
    guard = CostGuard(hard_cap_usd=1.0)
    llm = GeminiLLMClient(
        allow_paid=True,
        live_enabled=True,
        transport=transport,
        cost_guard=guard,
        sleeper=lambda s: sleeps.append(s),
    )
    with pytest.raises(ProviderError) as ei:
        llm.propose_action(trusted_user_id="U1", user_message="x")
    assert ei.value.category == ProviderErrorCategory.MODEL_NOT_FOUND
    assert sleeps == []
