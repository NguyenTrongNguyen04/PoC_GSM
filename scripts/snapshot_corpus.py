from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.pipeline import (
    PipelineError,
    load_snapshot_config,
    publish_existing_bundle,
    stage_snapshots,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Corpus snapshot pipeline (Pass B.1.1: stage OR publish-existing)"
    )
    parser.add_argument("--mode", choices=["offline", "live"], default=None)
    parser.add_argument("--fixture-dir", type=Path, default=PROJECT_ROOT / "tests/fixtures/corpus")
    parser.add_argument(
        "--publish-existing",
        type=Path,
        default=None,
        metavar="STAGING_DIR",
        help="Publish an already Research-approved staging bundle (no stage/fetch).",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=None,
        help="Optional staging root under artifacts/ for --mode stage.",
    )
    args = parser.parse_args()
    cfg = load_snapshot_config(PROJECT_ROOT)

    if args.publish_existing is not None and args.mode is not None:
        print("REFUSED: --publish-existing is mutually exclusive with --mode", file=sys.stderr)
        return 2
    if args.publish_existing is None and args.mode is None:
        print("REFUSED: provide --mode offline|live OR --publish-existing STAGING_DIR", file=sys.stderr)
        return 2

    if args.publish_existing is not None:
        if not bool(cfg.get("publish_enabled")):
            print("REFUSED: publish_enabled=false in config/corpus_snapshot.yaml", file=sys.stderr)
            return 2
        try:
            publish_existing_bundle(
                PROJECT_ROOT,
                args.publish_existing,
                allow_publish=True,
            )
        except PipelineError as exc:
            print(f"SNAPSHOT PUBLISH-EXISTING: FAILED\n{exc}", file=sys.stderr)
            return 1
        print("SNAPSHOT PIPELINE: PUBLISHED_EXISTING_OK")
        print(
            json.dumps(
                {
                    "published_snapshots": True,
                    "staged": False,
                    "fetched": False,
                    "staging_dir": str(args.publish_existing),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    mode = args.mode
    assert mode is not None
    if mode == "live" and not bool(cfg.get("live_fetch_enabled")):
        print("REFUSED: live_fetch_enabled=false in config/corpus_snapshot.yaml", file=sys.stderr)
        return 2

    staging_root = args.staging_dir
    if staging_root is None and mode == "live":
        staging_root = PROJECT_ROOT / "artifacts" / "live_staging"

    try:
        staged, docs, _rows = stage_snapshots(
            PROJECT_ROOT,
            mode=mode,
            fixture_dir=args.fixture_dir,
            staging_root=staging_root,
        )
    except PipelineError as exc:
        print(f"SNAPSHOT PIPELINE: FAILED\n{exc}", file=sys.stderr)
        return 1

    summary = {
        "mode": mode,
        "staged_units": len(docs),
        "artifact_dir": str(staged),
        "published_snapshots": False,
        "production_manifest_updated": False,
        "source_ids": [d.source_id for d in docs],
        "content_sha256": {d.source_id: d.content_sha256 for d in docs},
    }
    print("SNAPSHOT PIPELINE: STAGED_OK")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
