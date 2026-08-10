"""Research Lead only: mark a live staging bundle as research_approved for publish."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.provenance import ProvenanceError, mark_research_approved, read_provenance


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve live staging bundle (Research Lead)")
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "live_staging",
    )
    parser.add_argument("--reviewed-by", required=True, help="Research Lead identity")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--i-am-research-lead",
        action="store_true",
        help="Required attestation flag; Code Lead must not use this to self-approve.",
    )
    args = parser.parse_args()
    if not args.i_am_research_lead:
        print("REFUSED: missing --i-am-research-lead attestation", file=sys.stderr)
        return 2
    try:
        updated = mark_research_approved(
            args.staging_dir,
            project_root=PROJECT_ROOT,
            reviewed_by=args.reviewed_by,
            notes=args.notes,
        )
    except ProvenanceError as exc:
        print(f"APPROVE FAILED: {exc}", file=sys.stderr)
        return 1
    print("RESEARCH_APPROVAL: OK")
    print(json.dumps(updated.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
