from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_contracts.validation import ContractValidationError, validate_project


def main() -> int:
    try:
        summary = validate_project(PROJECT_ROOT)
    except ContractValidationError as exc:
        print("CONTRACT VALIDATION: FAILED", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print("CONTRACT VALIDATION: PASSED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
