#!/usr/bin/env python
"""Run Baseline B0 / B0.2A harness — FakeLLM default; Gemini gated (no live in this turn)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poc_runtime.gates import GateRefusal  # noqa: E402
from poc_runtime.runner import RunIsolationError, run_b0  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Baseline B0 / B0.2A runtime harness")
    p.add_argument("--split", default="development", choices=["development", "evaluation"])
    p.add_argument("--provider", default="fake", choices=["fake", "gemini"])
    p.add_argument("--run-id", required=True, help="Unique run id; refuses if directory exists")
    p.add_argument(
        "--allow-eval",
        action="store_true",
        help="Required to read evaluation split (read-only; never mutate scenarios)",
    )
    p.add_argument("--max-queries", type=int, default=None)
    p.add_argument("--out-dir", type=Path, default=None, help="Parent dir (default artifacts/b0_runs)")
    p.add_argument("--fixture", type=Path, default=None)
    p.add_argument(
        "--query-id",
        action="append",
        dest="query_ids",
        default=None,
        help="Explicit query id (repeatable). Required for gemini canary/preflight.",
    )
    p.add_argument("--budget-usd", type=float, default=None)
    p.add_argument("--allow-paid", action="store_true")
    p.add_argument("--confirm-live-call", default=None)
    p.add_argument(
        "--preflight",
        action="store_true",
        help="Gemini gate check only — zero network, no run directory / SQLite",
    )
    args = p.parse_args()

    try:
        result = run_b0(
            project_root=ROOT,
            split=args.split,
            provider=args.provider,
            allow_eval=args.allow_eval,
            run_id=args.run_id,
            out_dir=args.out_dir,
            max_queries=args.max_queries,
            fixture_path=args.fixture,
            query_ids=args.query_ids,
            budget_usd=args.budget_usd,
            allow_paid=args.allow_paid,
            confirm_live_call=args.confirm_live_call,
            preflight=args.preflight,
        )
    except GateRefusal as exc:
        print(str(exc))
        return 2
    except RunIsolationError as exc:
        print(str(exc))
        return 3

    if args.preflight:
        assert isinstance(result, dict)
        print("=== B0.2A Gemini preflight ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("network_called=false")
        return 0

    summary = result
    print("=== B0 run summary ===")
    print(f"split={summary.split}")
    print(f"provider={summary.provider}")
    print(f"purpose={summary.purpose}")
    print(f"quality_claim={str(summary.quality_claim).lower()}")
    print(f"run_id={summary.run_id}")
    print(f"scenarios_run={summary.scenarios_run}")
    print(f"queries_run={summary.queries_run}")
    print(f"traces_written={summary.traces_written}")
    print(f"missing_trace={summary.missing_trace_count}")
    print(f"initial_tickets_seeded={summary.initial_tickets_seeded}")
    print(f"scenario_isolation_violations={summary.scenario_isolation_violations}")
    print(f"cross_user_leakage={summary.cross_user_leakage}")
    print(f"invalid_transition_executed={summary.invalid_transition_executed}")
    print(
        f"policy allow/deny/clarify/none="
        f"{summary.policy_allow}/{summary.policy_deny}/{summary.policy_clarify}/{summary.policy_none}"
    )
    print(f"actions proposed/executed={summary.actions_proposed}/{summary.actions_executed}")
    print(f"action_type_counts={summary.action_type_counts}")
    print(f"fake_fixture_coverage={summary.fake_fixture_coverage}/{summary.queries_run}")
    print(
        "expected_action_type_accuracy="
        f"{summary.expected_action_type_matches}/{summary.expected_action_type_total} "
        f"({summary.expected_action_type_accuracy:.3f})"
    )
    print(f"policy_decision_matches={summary.policy_decision_matches}")
    avg = summary.latency_ms_total / summary.queries_run if summary.queries_run else 0.0
    print(f"latency_ms_avg={avg:.2f}")
    print(f"estimated_cost_usd={summary.estimated_cost_usd}")
    print(f"run_dir={summary.run_dir}")
    print(f"traces_path={summary.traces_path}")
    print(f"results_path={summary.results_path}")

    ok = (
        summary.missing_trace_count == 0
        and summary.error_count == 0
        and summary.scenario_isolation_violations == 0
        and summary.cross_user_leakage == 0
        and summary.invalid_transition_executed == 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
