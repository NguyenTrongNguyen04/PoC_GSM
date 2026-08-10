from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.validate_knowledge import KnowledgeValidationError, validate_knowledge


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate knowledge dataset / fact catalog")
    parser.add_argument(
        "--scope",
        choices=["offline-fixture", "production"],
        default="offline-fixture",
        help="offline-fixture uses fixture catalog; production uses skeleton catalog",
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--fixture-dir", type=Path, default=None)
    args = parser.parse_args()
    try:
        summary = validate_knowledge(
            PROJECT_ROOT,
            scope=args.scope,
            strict=args.strict,
            fixture_dir=args.fixture_dir,
        )
    except KnowledgeValidationError as exc:
        print("KNOWLEDGE VALIDATION: FAILED", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print("KNOWLEDGE VALIDATION: PASSED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
