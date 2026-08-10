"""Materialize selector-friendly HTML from Green SM Next.js payloads (v0.2.0)."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from poc_corpus.checksum import sha256_text
from poc_corpus.models import MATERIALIZER_VERSION


class MaterializeError(ValueError):
    pass


_USER_FAQ_MARKERS = ("người dùng", "nguoi dung", "for users", "user")
_REGULATION_ASSET_RE = re.compile(
    r"(?:https://www\.greensm\.com)?(/images/regulations/quychehoatdong-\d+\.jpg)"
)
_TAG_LITERAL_RE = re.compile(r"</?[a-zA-Z][^>]*>")


@dataclass
class MaterializeResult:
    html: str
    mode: str
    version: str = MATERIALIZER_VERSION
    payload_sha256: str = ""
    content_kind: str = "text"
    ocr_status: str | None = None
    text_retrieval_eligible: bool = True
    asset_urls: list[str] = field(default_factory=list)


def _escape(text: str) -> str:
    return html.escape(text or "", quote=True)


def assert_no_literal_html_tags(text: str, *, context: str) -> None:
    if _TAG_LITERAL_RE.search(text or ""):
        raise MaterializeError(f"{context}: literal HTML tags remain in text")


def rich_html_to_structured_text(raw: str) -> str:
    """Parse rich HTML into structured plain text/tables (no literal markup)."""
    if not raw:
        return ""
    if "<" not in raw and ">" not in raw:
        return raw.replace("\r\n", "\n").strip()

    soup = BeautifulSoup(raw, "lxml")
    chunks: list[str] = []

    def emit_table(table: Tag) -> None:
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                c.get_text(" ", strip=True)
                for c in tr.find_all(["th", "td"], recursive=False)
            ]
            if not cells:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            return
        width = max(len(r) for r in rows)
        norm = [r + [""] * (width - len(r)) for r in rows]
        chunks.append("TABLE")
        for r in norm:
            chunks.append(" | ".join(r))
        chunks.append("END_TABLE")

    body = soup.body or soup
    for el in body.children:
        if not isinstance(el, Tag):
            text = str(el).strip()
            if text:
                chunks.append(text)
            continue
        if el.name == "table":
            emit_table(el)
            continue
        for table in el.find_all("table"):
            emit_table(table)
            table.decompose()
        text = el.get_text("\n", strip=True)
        if text:
            chunks.append(text)

    if not chunks:
        chunks.append(soup.get_text("\n", strip=True))

    out = "\n".join(c for c in chunks if c).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    assert_no_literal_html_tags(out, context="rich_html_to_structured_text")
    return out


def _paragraphs_to_html(text: str) -> str:
    clean = rich_html_to_structured_text(text)
    chunks = [c.strip() for c in re.split(r"\r?\n\s*\r?\n", clean) if c.strip()]
    if not chunks:
        return f"<p>{_escape(clean)}</p>" if clean else ""
    return "".join(f"<p>{_escape(c)}</p>" for c in chunks)


def _pick_user_faq_root(set_up_faq: list[dict]) -> dict:
    for entry in set_up_faq:
        question = str(entry.get("question") or "").lower()
        if any(m in question for m in _USER_FAQ_MARKERS):
            return entry
    if not set_up_faq:
        raise MaterializeError("contentFaq.setUpFaq is empty")
    return set_up_faq[0]


def materialize_helps_faq(page_props: dict) -> str:
    content = page_props.get("contentFaq") or {}
    set_up = content.get("setUpFaq") or []
    root = _pick_user_faq_root(set_up)
    sections = root.get("setUpQuestion") or []
    parts = [
        "<!DOCTYPE html><html lang=\"vi\"><head><meta charset=\"utf-8\">"
        "<title>Trung tâm giải đáp | Green SM</title></head><body>",
        "<main id=\"content\">",
        "<h1>Trung tâm giải đáp | Các câu hỏi thường gặp</h1>",
    ]
    for sec_idx, section in enumerate(sections, start=1):
        title = str(section.get("title") or f"Section {sec_idx}").strip()
        parts.append(f'<section data-section="{sec_idx}">')
        parts.append(f"<h2>{sec_idx}. {_escape(title)}</h2>")
        for faq_idx, item in enumerate(section.get("setUpTitle") or [], start=1):
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            key = f"{sec_idx}.{faq_idx}"
            parts.append(f'<article data-faq="{key}">')
            parts.append(f"<h3>{key}. {_escape(label)}</h3>")
            parts.append(_paragraphs_to_html(value))
            parts.append("</article>")
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


def _terms_items_html(title: str, excerpt: str | None, items: list[dict]) -> str:
    parts = [
        "<!DOCTYPE html><html lang=\"vi\"><head><meta charset=\"utf-8\">"
        f"<title>{_escape(title)}</title></head><body>",
        "<main id=\"content\">",
        f"<h1>{_escape(title)}</h1>",
    ]
    if excerpt:
        parts.append(_paragraphs_to_html(excerpt))
    for item in items:
        item_title = str(item.get("title") or "").strip()
        desc = str(item.get("description") or "").strip()
        parts.append("<section>")
        if item_title:
            parts.append(f"<h2>{_escape(item_title)}</h2>")
        parts.append(_paragraphs_to_html(desc))
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


def materialize_general_terms(page_props: dict) -> str:
    block = page_props.get("generalTerms") or {}
    return _terms_items_html(
        str(block.get("generalTitle") or "Quy định chung"),
        None,
        list(block.get("generalItems") or []),
    )


def materialize_privacy(page_props: dict) -> str:
    block = page_props.get("privacyNotice") or {}
    return _terms_items_html(
        str(block.get("privacyTitle") or "Chính sách bảo vệ dữ liệu cá nhân"),
        block.get("privacyExcerpt"),
        list(block.get("privacyItems") or []),
    )


def materialize_service(page_props: dict) -> str:
    block = page_props.get("serviceData") or {}
    return _terms_items_html(
        str(block.get("serviceTitle") or "Điều khoản chung Hợp đồng Dịch vụ"),
        block.get("serviceExcerpt"),
        list(block.get("serviceItems") or []),
    )


def extract_regulation_asset_paths(source_text: str) -> list[str]:
    text = source_text or ""
    found = _REGULATION_ASSET_RE.findall(text)

    # Live Next.js chunk builds URLs dynamically, e.g.:
    # "/images/regulations/quychehoatdong-".concat(t+1,".jpg") with Array.from({length:56})
    if not found and "quychehoatdong-" in text and "/images/regulations/" in text:
        length_match = re.search(r"Array\.from\(\{\s*length\s*:\s*(\d+)\s*\}", text)
        template_match = re.search(
            r'["\'](/images/regulations/quychehoatdong-)["\']\s*\.concat\([^,]+,\s*["\']\.jpg["\']\)',
            text,
        )
        if length_match and template_match:
            n = int(length_match.group(1))
            prefix = template_match.group(1)
            if n > 0:
                found = [f"{prefix}{i}.jpg" for i in range(1, n + 1)]

    def _key(path: str) -> int:
        m = re.search(r"(\d+)\.jpg$", path)
        return int(m.group(1)) if m else 0

    return sorted(set(found), key=_key)


def discover_regulation_assets(
    html_text: str,
    *,
    canonical_url: str,
    fetch_text: Callable[[str], str] | None = None,
) -> list[str]:
    """Extract quyche image paths from page source and same-origin page scripts."""
    paths = extract_regulation_asset_paths(html_text)
    if paths:
        return paths

    soup = BeautifulSoup(html_text, "lxml")
    origin = f"{urlparse(canonical_url).scheme}://{urlparse(canonical_url).netloc}"
    if fetch_text is None:
        raise MaterializeError(
            "regulations has no asset list in page source and no fetch_text callback "
            "to load linked scripts"
        )
    for tag in soup.find_all("script", src=True):
        src = str(tag.get("src") or "")
        if "regulations" not in src:
            continue
        script_url = urljoin(origin + "/", src.lstrip("/"))
        try:
            body = fetch_text(script_url)
        except Exception as exc:
            raise MaterializeError(f"failed to fetch regulations script {script_url}: {exc}") from exc
        paths = extract_regulation_asset_paths(body)
        if paths:
            return paths

    raise MaterializeError("regulations has no asset list in source")


def materialize_regulations_images(
    canonical_url: str,
    asset_paths: list[str],
) -> tuple[str, list[str]]:
    if not asset_paths:
        raise MaterializeError("regulations has no asset list in source")
    origin = f"{urlparse(canonical_url).scheme}://{urlparse(canonical_url).netloc}"
    abs_urls = [urljoin(origin + "/", p.lstrip("/")) for p in asset_paths]
    # Image-only unit: short non-indexable provenance (excluded from text retrieval).
    lines = [
        "IMAGE_ONLY_DOCUMENT",
        "title: Quy chế hoạt động",
        "ocr_status: not_run",
        "text_retrieval_eligible: false",
        f"asset_count: {len(abs_urls)}",
        "assets:",
    ]
    lines.extend(f"- {u}" for u in abs_urls)
    body = "\n".join(lines)
    assert_no_literal_html_tags(body, context="regulations provenance")
    html_doc = (
        "<!DOCTYPE html><html lang=\"vi\"><head><meta charset=\"utf-8\">"
        "<title>Quy chế hoạt động | Green SM</title></head><body>"
        f"<main id=\"content\"><pre>{_escape(body)}</pre></main></body></html>"
    )
    return html_doc, abs_urls


def _load_next_data(html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError as exc:
        raise MaterializeError(f"invalid __NEXT_DATA__ JSON: {exc}") from exc


def materialize_html(
    html_text: str,
    *,
    canonical_url: str,
    fetch_text: Callable[[str], str] | None = None,
) -> MaterializeResult:
    """
    Return MaterializeResult for selectors.

    mode is 'identity' when fixtures/plain HTML are left unchanged.
    """
    path = urlparse(canonical_url).path.rstrip("/").lower()
    data = _load_next_data(html_text)

    if data is None:
        payload = sha256_text(html_text)
        return MaterializeResult(
            html=html_text,
            mode="identity",
            payload_sha256=payload,
        )

    page_props = (data.get("props") or {}).get("pageProps") or {}
    payload = sha256_text(json.dumps(page_props, sort_keys=True, ensure_ascii=False, default=str))

    if path.endswith("/helps") and page_props.get("contentFaq"):
        return MaterializeResult(
            html=materialize_helps_faq(page_props),
            mode="next_content_faq",
            payload_sha256=payload,
        )

    if path.endswith("/terms-policies/general") and page_props.get("generalTerms"):
        return MaterializeResult(
            html=materialize_general_terms(page_props),
            mode="next_general_terms",
            payload_sha256=payload,
        )

    if path.endswith("/terms-policies/privacy-notice") and page_props.get("privacyNotice"):
        return MaterializeResult(
            html=materialize_privacy(page_props),
            mode="next_privacy_notice",
            payload_sha256=payload,
        )

    if path.endswith("/terms-policies/service-agreement") and page_props.get("serviceData"):
        return MaterializeResult(
            html=materialize_service(page_props),
            mode="next_service_agreement",
            payload_sha256=payload,
        )

    if path.endswith("/terms-policies/regulations"):
        asset_paths = discover_regulation_assets(
            html_text, canonical_url=canonical_url, fetch_text=fetch_text
        )
        html_doc, abs_urls = materialize_regulations_images(canonical_url, asset_paths)
        return MaterializeResult(
            html=html_doc,
            mode="next_regulations_images",
            payload_sha256=sha256_text("\n".join(asset_paths)),
            content_kind="image_only",
            ocr_status="not_run",
            text_retrieval_eligible=False,
            asset_urls=abs_urls,
        )

    return MaterializeResult(html=html_text, mode="identity", payload_sha256=payload)
