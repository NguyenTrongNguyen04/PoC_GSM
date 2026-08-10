from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from poc_corpus.models import ExtractionStrategy
from poc_corpus.normalize import normalize_fragment_html


class SelectorError(ValueError):
    pass


@dataclass(frozen=True)
class SelectorResult:
    html_fragment: str
    extraction_strategy: ExtractionStrategy
    faq_range: list[str] | None = None


_FAQ_RE = re.compile(r"^faq:(?P<root>\d+)\.(?P<start>\d+)(?:-(?P<end_root>\d+)\.(?P<end>\d+))?$")
_SECTION_RE = re.compile(r"^section:(?P<num>\d+)$")
_FAQ_HEADING_RE = re.compile(r"^(?P<a>\d+)\.(?P<b>\d+)\.\s*(?P<title>.*)$")


def parse_selector(selector: str) -> dict:
    selector = selector.strip()
    if selector == "page":
        return {"kind": "page"}
    m = _FAQ_RE.match(selector)
    if m:
        start = (int(m.group("root")), int(m.group("start")))
        if m.group("end"):
            end = (int(m.group("end_root")), int(m.group("end")))
        else:
            end = start
        if end < start:
            raise SelectorError(f"invalid FAQ range: {selector}")
        return {"kind": "faq", "start": start, "end": end}
    m = _SECTION_RE.match(selector)
    if m:
        return {"kind": "section", "num": int(m.group("num"))}
    raise SelectorError(f"unsupported content_selector: {selector}")


def _faq_key(a: int, b: int) -> tuple[int, int]:
    return a, b


def _iter_faq_nodes(soup: BeautifulSoup) -> list[tuple[tuple[int, int], Tag]]:
    nodes: list[tuple[tuple[int, int], Tag]] = []
    for tag in soup.find_all(attrs={"data-faq": True}):
        raw = str(tag.get("data-faq"))
        parts = raw.split(".")
        if len(parts) != 2:
            continue
        nodes.append((_faq_key(int(parts[0]), int(parts[1])), tag))
    if nodes:
        return nodes
    # semantic headings without data-faq
    for tag in soup.find_all(["h2", "h3", "h4", "strong", "p"]):
        text = tag.get_text(" ", strip=True)
        m = _FAQ_HEADING_RE.match(text)
        if not m:
            continue
        key = _faq_key(int(m.group("a")), int(m.group("b")))
        nodes.append((key, tag))
    return nodes


def _collect_until_next_faq(start_tag: Tag) -> str:
    chunks = [str(start_tag)]
    for sibling in start_tag.next_siblings:
        if isinstance(sibling, Tag):
            if sibling.has_attr("data-faq"):
                break
            text = sibling.get_text(" ", strip=True)
            m = _FAQ_HEADING_RE.match(text)
            if m:
                break
            if sibling.name in {"h2"} and re.match(r"^\d+\.\s+", text):
                break
        chunks.append(str(sibling))
    return "".join(chunks)


def _expected_faq_keys(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    if start[0] != end[0]:
        raise SelectorError("FAQ range must stay within one section root (e.g. 4.1-4.4)")
    return [(start[0], i) for i in range(start[1], end[1] + 1)]


def _assert_contiguous_keys(found: list[tuple[int, int]], start: tuple[int, int], end: tuple[int, int]) -> None:
    expected = _expected_faq_keys(start, end)
    present = sorted(set(found))
    if present != expected:
        raise SelectorError(
            f"FAQ range must include contiguous IDs {expected}; found {present}"
        )


def _assert_section_boundary(fragment_html: str, num: int) -> None:
    """Reject any top-level section heading/data-section other than num (blocks 2→4 jumps)."""
    soup = BeautifulSoup(fragment_html, "lxml")
    for tag in soup.find_all(attrs={"data-section": True}):
        ds = str(tag.get("data-section"))
        if ds != str(num):
            raise SelectorError(f"section:{num} includes foreign data-section={ds}")
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(" ", strip=True)
        # Top-level section heading: "N. Title" (not FAQ "N.M. ...")
        m = re.match(r"^(\d+)\.\s+(?!\d)", text)
        if m:
            heading_num = int(m.group(1))
            if heading_num != num:
                raise SelectorError(
                    f"section:{num} leaked top-level section {heading_num}: {text}"
                )


def _faq_fragment(tag: Tag) -> str:
    """Include body siblings when data-faq is attached to a heading."""
    if tag.name == "article":
        return str(tag)
    if tag.name in {"h1", "h2", "h3", "h4", "strong"}:
        return _collect_until_next_faq(tag)
    if tag.has_attr("data-faq"):
        # Container without nested block body → expand siblings
        has_block = any(
            isinstance(child, Tag) and child.name in {"p", "div", "ul", "ol", "section", "article"}
            for child in tag.children
        )
        if not has_block:
            return _collect_until_next_faq(tag)
        return str(tag)
    return _collect_until_next_faq(tag)


def _dom_faq(soup: BeautifulSoup, start: tuple[int, int], end: tuple[int, int]) -> SelectorResult | None:
    nodes = _iter_faq_nodes(soup)
    if not nodes:
        return None
    wanted = [n for n in nodes if start <= n[0] <= end]
    if not wanted:
        return None
    keys = [k for k, _ in wanted]
    try:
        _assert_contiguous_keys(keys, start, end)
    except SelectorError:
        return None
    fragments = [_faq_fragment(tag) for _, tag in wanted]
    html = "\n".join(fragments)
    faq_range = [f"{a}.{b}" for a, b in _expected_faq_keys(start, end)]
    return SelectorResult(html, ExtractionStrategy.DOM_SEMANTIC, faq_range=faq_range)


def _dom_section(soup: BeautifulSoup, num: int) -> SelectorResult | None:
    section = soup.find(attrs={"data-section": str(num)})
    if section is not None:
        fragment = str(section)
        _assert_section_boundary(fragment, num)
        return SelectorResult(fragment, ExtractionStrategy.DOM_SEMANTIC)
    heading = None
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(" ", strip=True)
        if re.match(rf"^{num}\.\s+", text):
            heading = tag
            break
    if heading is None:
        return None
    chunks = [str(heading)]
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag) and sibling.name in {"h1", "h2"}:
            text = sibling.get_text(" ", strip=True)
            if re.match(rf"^{num + 1}\.\s+", text):
                break
            if re.match(r"^\d+\.\s+", text) and not _FAQ_HEADING_RE.match(text):
                break
        chunks.append(str(sibling))
    fragment = "".join(chunks)
    _assert_section_boundary(fragment, num)
    return SelectorResult(fragment, ExtractionStrategy.DOM_SEMANTIC)


def _dom_page(soup: BeautifulSoup) -> SelectorResult | None:
    main = soup.find("main") or soup.find(attrs={"id": "content"}) or soup.find("article")
    if main is None:
        return None
    return SelectorResult(str(main), ExtractionStrategy.DOM_SEMANTIC)


def _is_top_level_section_heading(line: str) -> int | None:
    """Return section number for 'N. Title' headings; ignore FAQ 'N.M. ...'."""
    m = re.match(r"^(\d+)\.\s+(?!\d)", line.strip())
    if not m:
        return None
    return int(m.group(1))


def _line_faq(text_lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> SelectorResult | None:
    pattern_start = re.compile(rf"^{start[0]}\.{start[1]}\.\s*")
    start_idx = next((i for i, line in enumerate(text_lines) if pattern_start.match(line.strip())), None)
    if start_idx is None:
        return None
    end_idx = len(text_lines)
    found_keys: list[tuple[int, int]] = []
    for i in range(start_idx, len(text_lines)):
        line = text_lines[i].strip()
        m = _FAQ_HEADING_RE.match(line)
        if m:
            key = (int(m.group("a")), int(m.group("b")))
            if key > end:
                end_idx = i
                break
            if start <= key <= end:
                found_keys.append(key)
            continue
        other = _is_top_level_section_heading(line)
        if other is not None and other != start[0]:
            end_idx = i
            break
    try:
        _assert_contiguous_keys(found_keys, start, end)
    except SelectorError:
        return None
    fragment_text = "\n".join(text_lines[start_idx:end_idx])
    html = f"<div>{fragment_text}</div>"
    faq_range = [f"{a}.{b}" for a, b in _expected_faq_keys(start, end)]
    return SelectorResult(html, ExtractionStrategy.LINE_FALLBACK, faq_range=faq_range)


def _line_section(text_lines: list[str], num: int) -> SelectorResult | None:
    start_idx = next((i for i, line in enumerate(text_lines) if re.match(rf"^{num}\.\s+", line.strip())), None)
    if start_idx is None:
        return None
    end_idx = len(text_lines)
    for i in range(start_idx + 1, len(text_lines)):
        other = _is_top_level_section_heading(text_lines[i])
        if other is not None and other != num:
            end_idx = i
            break
    fragment = f"<div>{chr(10).join(text_lines[start_idx:end_idx])}</div>"
    _assert_section_boundary(fragment, num)
    return SelectorResult(fragment, ExtractionStrategy.LINE_FALLBACK)


def _plaintext_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def extract_section(html: str, content_selector: str) -> SelectorResult:
    """Extract a retrieval unit. Never falls back to full page on FAQ miss."""
    parsed = parse_selector(content_selector)
    soup = BeautifulSoup(html, "lxml")
    kind = parsed["kind"]

    if kind == "page":
        result = _dom_page(soup)
        if result is None:
            # line/page fallback: body without chrome tags already handled in normalize
            body = soup.body or soup
            result = SelectorResult(str(body), ExtractionStrategy.LINE_FALLBACK)
        return result

    if kind == "section":
        result = _dom_section(soup, parsed["num"])
        if result is not None:
            return result
        result = _line_section(_plaintext_lines(html), parsed["num"])
        if result is None:
            raise SelectorError(f"section selector did not match: {content_selector}")
        return result

    # faq
    result = _dom_faq(soup, parsed["start"], parsed["end"])
    if result is not None:
        return result
    result = _line_faq(_plaintext_lines(html), parsed["start"], parsed["end"])
    if result is None:
        raise SelectorError(f"faq selector did not match: {content_selector}")
    return result


def extract_normalized(html: str, content_selector: str) -> tuple[str, SelectorResult]:
    result = extract_section(html, content_selector)
    text = normalize_fragment_html(result.html_fragment)
    if not text:
        raise SelectorError(f"empty normalized text for selector {content_selector}")
    return text, result
