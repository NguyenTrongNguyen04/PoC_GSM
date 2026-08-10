from __future__ import annotations

import re
import shutil
from pathlib import Path


SOURCE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")

# Exact staging directories that may be cleared entirely.
_ALLOWED_RMTREE_EXACT = frozenset(
    {
        "artifacts/offline_staging",
        "artifacts/live_staging",
        "artifacts/publish_backup",
    }
)
# Children under these prefixes may be removed (prefix root itself is not, except exact allowlist above).
_ALLOWED_RMTREE_UNDER = frozenset(
    {
        "artifacts/offline_staging",
        "artifacts/live_staging",
        "artifacts/publish_backup",
        "data/corpus/snapshots",
    }
)

_FORBIDDEN_EXACT = frozenset(
    {
        "",
        ".",
        "artifacts",
        "data",
        "data/corpus",
        "data/corpus/snapshots",
    }
)


class PathSafetyError(ValueError):
    pass


def validate_source_id(source_id: str) -> str:
    if not SOURCE_ID_RE.match(source_id or ""):
        raise PathSafetyError(f"invalid source_id: {source_id!r}")
    if ".." in source_id or "/" in source_id or "\\" in source_id:
        raise PathSafetyError(f"source_id path traversal rejected: {source_id!r}")
    return source_id


def ensure_within(base: Path, target: Path) -> Path:
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise PathSafetyError(
            f"path escapes allowed root: {target_resolved} not under {base_resolved}"
        ) from exc
    return target_resolved


def snapshot_path_for(base_dir: Path, source_id: str) -> Path:
    validate_source_id(source_id)
    base_dir = base_dir.resolve()
    candidate = (base_dir / f"{source_id}.json").resolve()
    return ensure_within(base_dir, candidate)


def _posix_rel(project_root: Path, path: Path) -> str:
    rel = path.resolve().relative_to(project_root.resolve())
    return rel.as_posix()


def safe_rmtree(path: Path, *, project_root: Path) -> None:
    """
    Delete only known staging directories under the project.
    Never deletes project root, artifacts root, or arbitrary caller paths.
    """
    if not path.exists():
        return
    project_root = project_root.resolve()
    resolved = path.resolve()
    if resolved == project_root:
        raise PathSafetyError("refusing rmtree of project root")
    try:
        rel = _posix_rel(project_root, resolved)
    except ValueError as exc:
        raise PathSafetyError(f"refusing rmtree outside project: {resolved}") from exc
    if rel in _FORBIDDEN_EXACT:
        raise PathSafetyError(f"refusing rmtree of protected path: {rel}")
    allowed = rel in _ALLOWED_RMTREE_EXACT or any(
        rel.startswith(prefix + "/") for prefix in _ALLOWED_RMTREE_UNDER
    )
    if not allowed:
        raise PathSafetyError(f"refusing rmtree outside allowed staging prefixes: {rel}")
    shutil.rmtree(resolved)


def resolve_artifacts_staging_dir(project_root: Path, staging_root: Path | None = None) -> Path:
    """Staging must resolve strictly under project_root/artifacts/ (not the artifacts root)."""
    artifacts = (project_root / "artifacts").resolve()
    if staging_root is None:
        candidate = (artifacts / "offline_staging").resolve()
    else:
        candidate = staging_root.resolve()
    try:
        rel = candidate.relative_to(artifacts)
    except ValueError as exc:
        raise PathSafetyError(
            f"staging_root must be under {artifacts}, got {candidate}"
        ) from exc
    if rel == Path("."):
        raise PathSafetyError("staging_root cannot be the artifacts root")
    return candidate


def confined_join(root: Path, *parts: str) -> Path:
    root_resolved = root.resolve()
    joined = root_resolved.joinpath(*parts)
    return ensure_within(root_resolved, joined)
