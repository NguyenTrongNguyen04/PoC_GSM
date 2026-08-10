from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from poc_runtime.llm.types import PROMPT_TEMPLATE_VERSION, RESPONSE_SCHEMA_VERSION

LIVE_CONFIRMATION_TOKEN = "RUN_3_QUERY_CANARY"
CANARY_QUERY_ALLOWLIST = (
    "P-DEV-01-Q01",
    "P-DEV-02-Q01",
    "SEC-DEV-01-Q01",
)
DEFAULT_CANARY_BUDGET_USD = 0.25
DEFAULT_CANARY_MAX_QUERIES = 3

EVAL_SHA = "dad9348245d46327f980f0221589f8a99fc3d9781e4f03a99682057ab7924be6"
MANIFEST_SHA = "ea9122c6c356b6f8715de5d05ac2679fa4fa945d47c3a7faacb141da3eac436c"
STAGED_BUNDLE_SHA = "860996a1460a905664cd87521c31510a5a5dfc0e8a9b1f077fd50600723b71cf"


class GateRefusal(RuntimeError):
    """CLI / runtime gate refusal — must not call network or create partial runs."""


@dataclass
class GeminiRuntimeConfig:
    live_enabled: bool = False
    max_canary_queries: int = DEFAULT_CANARY_MAX_QUERIES
    canary_budget_usd: float = DEFAULT_CANARY_BUDGET_USD
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    model_id: str = "gemini-3.5-flash-lite"
    model_runtime_validation: str = "pending_canary"


def load_gemini_config(project_root: Path) -> GeminiRuntimeConfig:
    path = project_root / "config" / "gemini.yaml"
    if not path.exists():
        return GeminiRuntimeConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    g = data.get("gemini") or data
    exp = yaml.safe_load((project_root / "config" / "experiment.yaml").read_text(encoding="utf-8")) or {}
    model_id = (
        ((exp.get("models") or {}).get("generation") or {}).get("model_id")
        or g.get("model_id")
        or "gemini-3.5-flash-lite"
    )
    return GeminiRuntimeConfig(
        live_enabled=bool(g.get("live_enabled", False)),
        max_canary_queries=int(g.get("max_canary_queries", DEFAULT_CANARY_MAX_QUERIES)),
        canary_budget_usd=float(g.get("canary_budget_usd", DEFAULT_CANARY_BUDGET_USD)),
        timeout_seconds=float(g.get("timeout_seconds", 30.0)),
        max_attempts=int(g.get("max_attempts", 3)),
        model_id=str(model_id),
        model_runtime_validation=str(g.get("model_runtime_validation", "pending_canary")),
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_protected_hashes(project_root: Path) -> dict[str, str]:
    eval_sha = sha256_file(project_root / "data/scenarios/scenarios_eval.yaml")
    man_sha = sha256_file(project_root / "data/corpus/corpus_manifest.csv")
    prov = yaml.safe_load  # placate linters
    import json

    provenance = json.loads(
        (project_root / "artifacts/live_staging/bundle_provenance.json").read_text(encoding="utf-8")
    )
    staged = str(provenance.get("staged_bundle_sha256") or "")
    if eval_sha != EVAL_SHA:
        raise GateRefusal(f"protected hash mismatch: scenarios_eval.yaml ({eval_sha})")
    if man_sha != MANIFEST_SHA:
        raise GateRefusal(f"protected hash mismatch: corpus_manifest.csv ({man_sha})")
    if staged != STAGED_BUNDLE_SHA:
        raise GateRefusal(f"protected hash mismatch: staged_bundle_sha256 ({staged})")
    _ = prov
    return {
        "scenarios_eval_sha256": eval_sha,
        "corpus_manifest_sha256": man_sha,
        "staged_bundle_sha256": staged,
        "promotion_status": str(provenance.get("promotion_status")),
        "approved_bundle_sha256": provenance.get("approved_bundle_sha256"),
    }


def api_key_present() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def validate_gemini_invocation_gates(
    *,
    project_root: Path,
    split: str,
    provider: str,
    allow_paid: bool,
    confirm_live_call: str | None,
    query_ids: list[str] | None,
    budget_usd: float | None,
    preflight: bool,
) -> dict[str, Any]:
    """Fail-closed gate checks. Does not create run directories or call network."""
    if provider != "gemini":
        return {"provider": provider, "gates_applicable": False}

    cfg = load_gemini_config(project_root)
    hashes = verify_protected_hashes(project_root)
    report: dict[str, Any] = {
        "provider": "gemini",
        "split": split,
        "preflight": preflight,
        "live_enabled": cfg.live_enabled,
        "allow_paid": allow_paid,
        "confirm_live_call_ok": confirm_live_call == LIVE_CONFIRMATION_TOKEN,
        "api_key_present": api_key_present(),
        "model_id": cfg.model_id,
        "model_runtime_validation": cfg.model_runtime_validation,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "response_schema_version": RESPONSE_SCHEMA_VERSION,
        "timeout_seconds": cfg.timeout_seconds,
        "max_attempts": cfg.max_attempts,
        "budget_usd": budget_usd,
        "canary_budget_usd": cfg.canary_budget_usd,
        "query_ids": list(query_ids or []),
        "protected_hashes": hashes,
        "network_called": False,
        "planned_max_cost_usd": min(
            float(budget_usd if budget_usd is not None else cfg.canary_budget_usd),
            cfg.canary_budget_usd,
        ),
    }

    if split != "development":
        raise GateRefusal("REFUSED: gemini provider only allowed on development split")

    qids = list(query_ids or [])
    if not qids:
        raise GateRefusal("REFUSED: gemini requires explicit --query-id (repeatable)")
    if len(qids) > cfg.max_canary_queries:
        raise GateRefusal(
            f"REFUSED: gemini canary allows at most {cfg.max_canary_queries} queries"
        )
    unknown = [q for q in qids if q not in CANARY_QUERY_ALLOWLIST]
    if unknown:
        raise GateRefusal(f"REFUSED: query_id not in canary allowlist: {unknown}")

    if budget_usd is not None and budget_usd > cfg.canary_budget_usd:
        raise GateRefusal(
            f"REFUSED: --budget-usd {budget_usd} exceeds canary cap {cfg.canary_budget_usd}"
        )

    if preflight:
        report["status"] = "preflight_ok"
        return report

    # Live path gates (still must not be used in B0.2A implementation turn)
    if not cfg.live_enabled:
        raise GateRefusal("REFUSED: gemini.live_enabled=false")
    if not allow_paid:
        raise GateRefusal("REFUSED: missing --allow-paid")
    if confirm_live_call != LIVE_CONFIRMATION_TOKEN:
        raise GateRefusal("REFUSED: invalid or missing --confirm-live-call token")
    if not api_key_present():
        raise GateRefusal("REFUSED: GEMINI_API_KEY missing in environment")

    report["status"] = "live_gates_ok"
    return report
