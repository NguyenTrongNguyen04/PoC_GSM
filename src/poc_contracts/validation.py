from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import yaml


EXPECTED_CATEGORY_COUNTS = {
    "Policy": 6,
    "State": 6,
    "Hybrid": 8,
    "SecurityLifecycle": 4,
}
REQUIRED_BASELINES = {"B0", "B1", "B3", "B4"}


class ContractValidationError(ValueError):
    pass


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_project(project_root: Path) -> dict:
    errors: list[str] = []
    personas_doc = _load_yaml(project_root / "data/personas/personas.yaml")
    dev_doc = _load_yaml(project_root / "data/scenarios/scenarios_dev.yaml")
    eval_doc = _load_yaml(project_root / "data/scenarios/scenarios_eval.yaml")
    baselines_doc = _load_yaml(project_root / "config/baselines.yaml")
    policy_doc = _load_yaml(project_root / "config/policy.yaml")
    experiment_doc = _load_yaml(project_root / "config/experiment.yaml")

    with (project_root / "data/corpus/corpus_manifest.csv").open("r", encoding="utf-8-sig", newline="") as f:
        corpus = list(csv.DictReader(f))
    doc_ids = {row["source_id"] for row in corpus}

    personas = personas_doc["personas"]
    dev = dev_doc["scenarios"]
    held_out = eval_doc["scenarios"]
    all_scenarios = dev + held_out

    if not personas_doc.get("is_fully_synthetic"):
        errors.append("personas dataset must be fully synthetic")
    if len(personas) != 8:
        errors.append(f"expected 8 personas, got {len(personas)}")
    if len(dev) != 12 or len(held_out) != 12:
        errors.append(f"expected 12 dev + 12 held-out scenarios, got {len(dev)} + {len(held_out)}")
    if len(corpus) != 18:
        errors.append(f"expected 18 corpus retrieval units, got {len(corpus)}")

    persona_ids = [p["persona_id"] for p in personas]
    if len(set(persona_ids)) != len(persona_ids):
        errors.append("persona_id values must be unique")
    dev_personas = {p["persona_id"] for p in personas if p["split"] == "development"}
    eval_personas = {p["persona_id"] for p in personas if p["split"] == "held_out"}
    if dev_personas & eval_personas:
        errors.append("development and held-out personas overlap")
    if len(dev_personas) != 4 or len(eval_personas) != 4:
        errors.append("expected 4 dev and 4 held-out personas")

    scenario_ids = [s["scenario_id"] for s in all_scenarios]
    if len(set(scenario_ids)) != 24:
        errors.append("scenario_id values must be 24 unique IDs")
    query_ids: list[str] = []
    category_counts = Counter()
    persona_scenario_counts = Counter()
    missing_docs: set[str] = set()

    for s in all_scenarios:
        category_counts[s["category"]] += 1
        persona_scenario_counts[s["persona_id"]] += 1
        expected_split = "development" if s in dev else "held_out"
        if s["split"] != expected_split:
            errors.append(f"{s['scenario_id']}: split mismatch")
        if s["smoke"] != (expected_split == "development"):
            errors.append(f"{s['scenario_id']}: smoke flag mismatch")
        if s["persona_id"] not in (dev_personas if expected_split == "development" else eval_personas):
            errors.append(f"{s['scenario_id']}: persona is assigned to the wrong split")
        if len(s["turns"]) not in {2, 3}:
            errors.append(f"{s['scenario_id']}: expected 2 or 3 turns")
        for t in s["turns"]:
            query_ids.append(t["query_id"])
            for source_id in t["ground_truth"]["expected_doc_ids"]:
                if source_id not in doc_ids:
                    missing_docs.add(source_id)

    if category_counts != Counter(EXPECTED_CATEGORY_COUNTS):
        errors.append(f"category allocation mismatch: {dict(category_counts)}")
    if len(query_ids) != 60 or len(set(query_ids)) != 60:
        errors.append(f"expected 60 unique query points, got {len(query_ids)} / {len(set(query_ids))} unique")
    if sum(len(s["turns"]) for s in dev) != 30 or sum(len(s["turns"]) for s in held_out) != 30:
        errors.append("expected 30 query points per split")
    if any(count != 3 for count in persona_scenario_counts.values()) or len(persona_scenario_counts) != 8:
        errors.append(f"each persona must own 3 scenarios: {dict(persona_scenario_counts)}")
    if missing_docs:
        errors.append(f"ground truth references unknown source IDs: {sorted(missing_docs)}")

    declared_persona_map = {p["persona_id"]: set(p["scenario_ids"]) for p in personas}
    actual_persona_map = {
        pid: {s["scenario_id"] for s in all_scenarios if s["persona_id"] == pid}
        for pid in persona_ids
    }
    if declared_persona_map != actual_persona_map:
        errors.append("persona scenario_ids do not match scenario assignments")

    baseline_ids = {b["id"] for b in baselines_doc["baselines"] if b.get("required")}
    if baseline_ids != REQUIRED_BASELINES:
        errors.append(f"required baselines must be {sorted(REQUIRED_BASELINES)}")
    if experiment_doc["budget"]["hard_cap_usd"] > 15:
        errors.append("budget hard cap exceeds approved 15 USD")
    if policy_doc["ticket"]["allowed_transitions"].get("CLOSED") != []:
        errors.append("CLOSED must have no outgoing transition in PoC")
    if not policy_doc["memory"].get("ticket_store_wins_conflict"):
        errors.append("Ticket Store must win memory conflicts")

    summary = {
        "contract_version": experiment_doc["contract_version"],
        "corpus_retrieval_units": len(corpus),
        "distinct_corpus_urls": len({row["canonical_url"] for row in corpus}),
        "personas": len(personas),
        "scenarios": len(all_scenarios),
        "development_scenarios": len(dev),
        "held_out_scenarios": len(held_out),
        "query_points": len(query_ids),
        "category_counts": dict(category_counts),
        "required_baselines": sorted(baseline_ids),
        "errors": errors,
    }
    if errors:
        raise ContractValidationError("\n".join(errors))
    return summary
