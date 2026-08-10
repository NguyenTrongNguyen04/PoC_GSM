from __future__ import annotations

import re
from bs4 import BeautifulSoup, NavigableString, Tag

from poc_corpus.checksum import nfc


CHROME_TAGS = {"nav", "header", "footer", "script", "style", "noscript", "form"}
CHROME_PHRASES = (
    "TÌM KIẾM",
    "Hotline: 1555",
    "All rights reserved",
    "CÔNG TY CỔ PHẦN DI CHUYỂN XANH",
    "Menu điều hướng chính",
)


def _visible_text(node: Tag) -> str:
    parts: list[str] = []
    for element in node.descendants:
        if isinstance(element, NavigableString):
            parent = element.parent
            if parent and parent.name in {"script", "style", "noscript"}:
                continue
            text = str(element).strip()
            if text:
                parts.append(text)
        elif isinstance(element, Tag) and element.name in {"p", "h1", "h2", "h3", "h4", "li", "br"}:
            parts.append("\n")
    joined = "\n".join(line.strip() for line in " ".join(parts).splitlines() if line.strip())
    joined = re.sub(r"[ \t]+", " ", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return nfc(joined.strip())


def strip_chrome(soup: BeautifulSoup) -> BeautifulSoup:
    for tag_name in CHROME_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    return soup


def normalize_fragment_html(html_fragment: str) -> str:
    soup = BeautifulSoup(html_fragment, "lxml")
    strip_chrome(soup)
    text = _visible_text(soup.body if soup.body else soup)
    lowered = text
    for phrase in CHROME_PHRASES:
        # Case-insensitive phrase removal while preserving surrounding text
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        lowered = pattern.sub("", lowered)
    text = lowered
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return nfc(text.strip())


def looks_like_chrome(text: str) -> bool:
    lowered = text.lower()
    return any(p.lower() in lowered for p in CHROME_PHRASES)
