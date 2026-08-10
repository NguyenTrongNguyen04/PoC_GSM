from __future__ import annotations

import hashlib
import unicodedata


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def sha256_text(text: str) -> str:
    return hashlib.sha256(nfc(text).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def codepoint_span(text: str, quote: str) -> tuple[int, int]:
    """Return inclusive-exclusive Unicode code-point offsets after NFC."""
    haystack = nfc(text)
    needle = nfc(quote)
    idx = haystack.find(needle)
    if idx < 0:
        raise ValueError("quote is not a substring of normalized text")
    return idx, idx + len(needle)


def slice_codepoints(text: str, start: int, end: int) -> str:
    normalized = nfc(text)
    return normalized[start:end]
