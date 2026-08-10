from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml

from poc_corpus.checksum import sha256_bytes, sha256_text
from poc_corpus.fetch import FetchError, FetchResult, fetch_url, validate_fetch_payload
from poc_corpus.materialize import MaterializeError, materialize_html
from poc_corpus.models import (
    MATERIALIZER_VERSION,
    PARSER_CONTRACT_VERSION,
    ManifestRow,
    RetrievalRole,
    SnapshotDocument,
)
from poc_corpus.paths import (
    PathSafetyError,
    resolve_artifacts_staging_dir,
    snapshot_path_for,
    validate_source_id,
)
from poc_corpus.persist import (
    PublishError,
    clear_dir,
    publish_staged_transaction,
    read_manifest,
    write_manifest,
    write_snapshot_json,
)
from poc_corpus.provenance import (
    BundleProvenance,
    ProvenanceError,
    assert_publishable_live_provenance,
    compute_staging_bundle_digest,
    config_sha256,
    new_run_id,
    now_iso,
    read_provenance,
    write_provenance,
)
from poc_corpus.selectors import extract_normalized
from poc_corpus.bundle import load_expected_source_ids, BundleValidationError


class PipelineError(RuntimeError):
    pass


def load_snapshot_config(project_root: Path) -> dict:
    path = project_root / "config/corpus_snapshot.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def _role_for(source_id: str, cfg: dict) -> tuple[RetrievalRole, str | None]:
    roles = cfg.get("retrieval_roles") or {}
    entry = roles.get(source_id) or {}
    role = RetrievalRole(entry.get("retrieval_role", "standalone"))
    parent = entry.get("parent_source_id")
    return role, parent


def build_url_fixture_map(fixture_dir: Path) -> dict[str, Path]:
    mapping = {
        "https://www.greensm.com/vn-vi/helps": fixture_dir / "helps_sample.html",
        "https://www.greensm.com/vn-vi/terms-policies/general": fixture_dir / "terms_general_sample.html",
        "https://www.greensm.com/vn-vi/terms-policies/regulations": fixture_dir / "terms_regulations_sample.html",
        "https://www.greensm.com/vn-vi/terms-policies/privacy-notice": fixture_dir / "terms_privacy_sample.html",
        "https://www.greensm.com/vn-vi/terms-policies/service-agreement": fixture_dir / "terms_service_sample.html",
    }
    missing = [str(p) for p in mapping.values() if not p.exists()]
    if missing:
        raise PipelineError(f"missing fixtures: {missing}")
    return mapping


def _fetch_offline(url: str, fixture_map: dict[str, Path], cfg: dict) -> FetchResult:
    path = fixture_map.get(url)
    if path is None:
        raise PipelineError(f"no offline fixture for URL: {url}")
    body = path.read_bytes()
    content_type = "text/html; charset=utf-8"
    validate_fetch_payload(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type=content_type,
        body=body,
        allowed_hosts=cfg["fetch"]["allowed_hosts"],
        require_https=bool(cfg["fetch"].get("require_https", True)),
        max_response_bytes=int(cfg["fetch"]["max_response_bytes"]),
        redirect_hops=(),
    )
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type=content_type,
        body=body,
        raw_sha256=sha256_bytes(body),
        source_last_modified=None,
        from_cache=True,
        redirect_hops=(),
    )


def _fetch_live(url: str, cfg: dict, cache_dir: Path) -> FetchResult:
    fetch_cfg = cfg["fetch"]
    try:
        return fetch_url(
            url,
            allowed_hosts=list(fetch_cfg["allowed_hosts"]),
            require_https=bool(fetch_cfg.get("require_https", True)),
            timeout_connect=float(fetch_cfg["timeout_connect_seconds"]),
            timeout_read=float(fetch_cfg["timeout_read_seconds"]),
            max_retries=int(fetch_cfg["max_retries"]),
            backoff_seconds=[float(x) for x in fetch_cfg.get("backoff_seconds") or [1, 2, 4]],
            max_response_bytes=int(fetch_cfg["max_response_bytes"]),
            user_agent=str(fetch_cfg.get("user_agent") or "green-sm-rag-mag-poc"),
            honor_retry_after=bool(fetch_cfg.get("honor_retry_after", True)),
            cache_dir=cache_dir,
            prefer_cache=False,
            max_redirects=int(fetch_cfg.get("max_redirects", 5)),
        )
    except FetchError as exc:
        raise PipelineError(str(exc)) from exc


def _make_script_fetcher(cfg: dict) -> Callable[[str], str]:
    fetch_cfg = cfg["fetch"]
    allowed = list(fetch_cfg["allowed_hosts"])
    timeout = httpx.Timeout(
        float(fetch_cfg["timeout_read_seconds"]),
        connect=float(fetch_cfg["timeout_connect_seconds"]),
    )
    headers = {
        "User-Agent": str(fetch_cfg.get("user_agent") or "green-sm-rag-mag-poc"),
        "Accept": "*/*",
    }

    def fetch_text(url: str) -> str:
        from poc_corpus.fetch import assert_allowed_url

        assert_allowed_url(url, allowed, require_https=bool(fetch_cfg.get("require_https", True)))
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            response = client.get(url)
            if response.status_code != 200:
                raise MaterializeError(f"script fetch HTTP {response.status_code} for {url}")
            return response.text

    return fetch_text


def stage_snapshots(
    project_root: Path,
    *,
    mode: str = "offline",
    fixture_dir: Path | None = None,
    staging_root: Path | None = None,
) -> tuple[Path, list[SnapshotDocument], list[ManifestRow]]:
    """Build all 18 snapshots under project_root/artifacts/ only."""
    if mode not in {"offline", "live"}:
        raise PipelineError(f"unsupported mode: {mode}")

    cfg = load_snapshot_config(project_root)
    if mode == "live" and not bool(cfg.get("live_fetch_enabled")):
        raise PipelineError("live fetch disabled in config/corpus_snapshot.yaml")

    try:
        expected_ids = load_expected_source_ids(project_root)
    except BundleValidationError as exc:
        raise PipelineError(str(exc)) from exc

    manifest_path = project_root / cfg["paths"]["manifest"]
    rows = read_manifest(manifest_path)
    row_ids = [r.source_id for r in rows]
    if row_ids != expected_ids:
        raise PipelineError(
            "production manifest source_id order/set must match immutable corpus contract"
        )

    for row in rows:
        try:
            validate_source_id(row.source_id)
        except PathSafetyError as exc:
            raise PipelineError(str(exc)) from exc

    try:
        artifact_root = resolve_artifacts_staging_dir(project_root, staging_root)
    except PathSafetyError as exc:
        raise PipelineError(str(exc)) from exc

    staging_snapshots = artifact_root / "by_source"
    clear_dir(artifact_root, project_root=project_root)
    staging_snapshots.mkdir(parents=True, exist_ok=True)

    unique_urls = list(dict.fromkeys(r.canonical_url for r in rows))
    fetched: dict[str, FetchResult] = {}
    script_fetcher = None
    if mode == "offline":
        fixture_map = build_url_fixture_map(fixture_dir or project_root / "tests/fixtures/corpus")
        for url in unique_urls:
            fetched[url] = _fetch_offline(url, fixture_map, cfg)
    else:
        cache_dir = project_root / cfg["paths"]["raw_cache_dir"]
        delay = float(cfg["fetch"].get("inter_url_delay_seconds") or 0)
        script_fetcher = _make_script_fetcher(cfg)
        for i, url in enumerate(unique_urls):
            if i and delay > 0:
                time.sleep(delay)
            fetched[url] = _fetch_live(url, cfg, cache_dir)

    docs: list[SnapshotDocument] = []
    staged_rows: list[ManifestRow] = []
    for row in rows:
        fetch = fetched[row.canonical_url]
        raw_html = fetch.body.decode("utf-8", errors="replace")
        try:
            materialized = materialize_html(
                raw_html,
                canonical_url=row.canonical_url,
                fetch_text=script_fetcher,
            )
        except MaterializeError as exc:
            raise PipelineError(f"{row.source_id}: materialize failed: {exc}") from exc
        text, extracted = extract_normalized(materialized.html, row.content_selector)
        # Terms/FAQ normalized text must not retain literal HTML tags.
        if "<" in text and any(tag in text for tag in ("</", "<p", "<div", "<table", "<br")):
            raise PipelineError(f"{row.source_id}: normalized_text still contains literal HTML tags")
        role, parent = _role_for(row.source_id, cfg)
        tags = [t for t in row.topic_tags.split(",") if t]
        doc = SnapshotDocument(
            source_id=row.source_id,
            title=row.title,
            canonical_url=row.canonical_url,
            requested_url=fetch.requested_url,
            final_url=fetch.final_url,
            content_selector=row.content_selector,
            language=row.language or "vi",
            publisher=row.publisher or "Green SM",
            fetched_at=_now_iso(),
            http_status=fetch.status_code,
            content_type=fetch.content_type,
            raw_sha256=fetch.raw_sha256,
            content_sha256=sha256_text(text),
            extraction_strategy=extracted.extraction_strategy,
            source_last_modified=fetch.source_last_modified,
            parser_version=str(cfg.get("parser_version") or PARSER_CONTRACT_VERSION),
            normalizer_version=str(cfg.get("normalizer_version") or "0.1.0"),
            materializer_version=str(cfg.get("materializer_version") or MATERIALIZER_VERSION),
            materialization_mode=materialized.mode,
            materialization_payload_sha256=materialized.payload_sha256,
            content_kind=materialized.content_kind,
            ocr_status=materialized.ocr_status,
            text_retrieval_eligible=materialized.text_retrieval_eligible,
            asset_urls=list(materialized.asset_urls),
            normalized_text=text,
            char_count=len(text),
            topic_tags=tags,
            priority=row.priority or "medium",
            retrieval_role=role,
            parent_source_id=parent,
            faq_range=extracted.faq_range,
        )
        write_snapshot_json(snapshot_path_for(staging_snapshots, row.source_id), doc)
        docs.append(doc)
        staged_rows.append(
            row.model_copy(
                update={
                    "snapshot_status": "snapshotted",
                    "fetched_at": doc.fetched_at,
                    "sha256": doc.content_sha256,
                }
            )
        )

    if len(docs) != 18:
        raise PipelineError("staging incomplete: expected 18 documents")
    write_manifest(artifact_root / "corpus_manifest.csv", staged_rows)

    try:
        digest, file_map = compute_staging_bundle_digest(artifact_root, project_root=project_root)
    except ProvenanceError as exc:
        raise PipelineError(str(exc)) from exc

    promotion = (
        "staged_pending_research_approval" if mode == "live" else "not_promotable"
    )
    provenance = BundleProvenance(
        data_origin=mode,  # type: ignore[arg-type]
        run_id=new_run_id(),
        materializer_version=str(cfg.get("materializer_version") or MATERIALIZER_VERSION),
        config_sha256=config_sha256(project_root),
        raw_sha256_by_url={url: fetched[url].raw_sha256 for url in unique_urls},
        created_at=now_iso(),
        promotion_status=promotion,  # type: ignore[arg-type]
        staged_bundle_sha256=digest,
        approved_bundle_sha256=None,
        bundle_file_sha256_by_path=file_map,
    )
    write_provenance(artifact_root, provenance)
    return artifact_root, docs, staged_rows


def publish_existing_bundle(
    project_root: Path,
    staging_root: Path,
    *,
    allow_publish: bool = False,
) -> None:
    """
    Publish an already-staged Research-approved live bundle.
    Never stages or fetches. Requires publish_enabled only (not live_fetch_enabled).
    """
    cfg = load_snapshot_config(project_root)
    if not allow_publish:
        raise PipelineError("publish_existing refused (allow_publish=False)")
    if not bool(cfg.get("publish_enabled")):
        raise PipelineError("publish disabled in config/corpus_snapshot.yaml")

    try:
        staging_root = resolve_artifacts_staging_dir(project_root, staging_root)
    except PathSafetyError as exc:
        raise PipelineError(str(exc)) from exc

    try:
        provenance = read_provenance(staging_root)
        assert_publishable_live_provenance(
            provenance, staging_root=staging_root, project_root=project_root
        )
    except ProvenanceError as exc:
        raise PipelineError(str(exc)) from exc

    target = project_root / cfg["paths"]["snapshots_dir"]
    staged_snapshots = staging_root / "by_source"
    backup_root = project_root / cfg["paths"]["publish_backup_dir"]
    try:
        publish_staged_transaction(
            project_root=project_root,
            staging_snapshots=staged_snapshots,
            target_snapshots=target,
            staging_manifest=staging_root / "corpus_manifest.csv",
            production_manifest=project_root / cfg["paths"]["manifest"],
            backup_root=backup_root,
            expected_count=18,
            post_validate=True,
        )
    except PublishError as exc:
        raise PipelineError(str(exc)) from exc


def publish_staged(
    project_root: Path,
    staging_root: Path,
    *,
    allow_publish: bool = False,
    staging_mode: str | None = None,
) -> None:
    """
    Compatibility wrapper: publish existing live Research-approved staging only.
    Does not stage or fetch. Prefer publish_existing_bundle explicitly.
    """
    if staging_mode is not None and staging_mode != "live":
        raise PipelineError("publish refused: mode != live")
    publish_existing_bundle(
        project_root, staging_root, allow_publish=allow_publish
    )
