from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from poc_corpus.checksum import sha256_bytes


class FetchError(RuntimeError):
    pass


HTML_MIME_EXACT = frozenset({"text/html", "application/xhtml+xml"})
MAX_RETRY_AFTER_SECONDS = 60.0


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    raw_sha256: str
    source_last_modified: str | None
    from_cache: bool = False
    redirect_hops: tuple[str, ...] = ()


def assert_allowed_url(url: str, allowed_hosts: list[str], require_https: bool = True) -> None:
    parsed = urlparse(url)
    if require_https and parsed.scheme != "https":
        raise FetchError(f"only HTTPS allowed: {url}")
    if parsed.hostname not in allowed_hosts:
        raise FetchError(f"host not allowlisted: {parsed.hostname}")


def assert_html_content_type(content_type: str) -> None:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in HTML_MIME_EXACT:
        raise FetchError(f"HTML MIME required, got: {content_type!r}")


def clamp_retry_after(raw: str | None, fallback: float) -> float:
    if raw is None:
        return fallback
    try:
        delay = float(raw)
    except ValueError:
        return fallback
    if delay < 0:
        return fallback
    return min(delay, MAX_RETRY_AFTER_SECONDS)


def validate_fetch_payload(
    *,
    requested_url: str,
    final_url: str,
    status_code: int,
    content_type: str,
    body: bytes,
    allowed_hosts: list[str],
    require_https: bool,
    max_response_bytes: int,
    redirect_hops: tuple[str, ...] = (),
) -> None:
    assert_allowed_url(requested_url, allowed_hosts, require_https=require_https)
    assert_allowed_url(final_url, allowed_hosts, require_https=require_https)
    for hop in redirect_hops:
        assert_allowed_url(hop, allowed_hosts, require_https=require_https)
    if status_code != 200:
        raise FetchError(f"expected HTTP 200, got {status_code}")
    assert_html_content_type(content_type)
    if len(body) > max_response_bytes:
        raise FetchError(f"response too large: {len(body)} bytes")
    if len(body) == 0:
        raise FetchError("empty response body")


def _stream_body_from_response(response: httpx.Response, max_response_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_response_bytes:
            response.close()
            raise FetchError(f"response exceeded max_response_bytes={max_response_bytes}")
        chunks.append(chunk)
    return b"".join(chunks)


def load_raw_cache(
    cache_dir: Path,
    url: str,
    *,
    allowed_hosts: list[str],
    require_https: bool,
    max_response_bytes: int,
) -> FetchResult | None:
    key = sha256_bytes(url.encode("utf-8"))
    path = cache_dir / f"{key}.html"
    meta = cache_dir / f"{key}.meta"
    if not path.exists() or not meta.exists():
        return None
    body = path.read_bytes()
    final_url = url
    content_type = "application/octet-stream"
    status = 0
    last_modified = None
    hops: list[str] = []
    for line in meta.read_text(encoding="utf-8").splitlines():
        if line.startswith("final_url="):
            final_url = line.split("=", 1)[1]
        elif line.startswith("content_type="):
            content_type = line.split("=", 1)[1]
        elif line.startswith("status="):
            status = int(line.split("=", 1)[1])
        elif line.startswith("last_modified="):
            val = line.split("=", 1)[1]
            last_modified = val or None
        elif line.startswith("redirect_hop="):
            hops.append(line.split("=", 1)[1])
    validate_fetch_payload(
        requested_url=url,
        final_url=final_url,
        status_code=status,
        content_type=content_type,
        body=body,
        allowed_hosts=allowed_hosts,
        require_https=require_https,
        max_response_bytes=max_response_bytes,
        redirect_hops=tuple(hops),
    )
    return FetchResult(
        requested_url=url,
        final_url=final_url,
        status_code=status,
        content_type=content_type,
        body=body,
        raw_sha256=sha256_bytes(body),
        source_last_modified=last_modified,
        from_cache=True,
        redirect_hops=tuple(hops),
    )


def save_raw_cache(cache_dir: Path, result: FetchResult) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = sha256_bytes(result.requested_url.encode("utf-8"))
    (cache_dir / f"{key}.html").write_bytes(result.body)
    lines = [
        f"final_url={result.final_url}",
        f"content_type={result.content_type}",
        f"status={result.status_code}",
        f"last_modified={result.source_last_modified or ''}",
    ]
    lines.extend(f"redirect_hop={hop}" for hop in result.redirect_hops)
    (cache_dir / f"{key}.meta").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_url(
    url: str,
    *,
    allowed_hosts: list[str],
    require_https: bool = True,
    timeout_connect: float = 10.0,
    timeout_read: float = 30.0,
    max_retries: int = 3,
    backoff_seconds: list[float] | None = None,
    max_response_bytes: int = 5_000_000,
    user_agent: str = "green-sm-rag-mag-poc/0.1.0",
    honor_retry_after: bool = True,
    cache_dir: Path | None = None,
    prefer_cache: bool = False,
    max_redirects: int = 5,
) -> FetchResult:
    assert_allowed_url(url, allowed_hosts, require_https=require_https)
    if prefer_cache and cache_dir is not None:
        cached = load_raw_cache(
            cache_dir,
            url,
            allowed_hosts=allowed_hosts,
            require_https=require_https,
            max_response_bytes=max_response_bytes,
        )
        if cached is not None:
            return cached

    backoff = backoff_seconds or [1.0, 2.0, 4.0]
    timeout = httpx.Timeout(timeout_read, connect=timeout_connect)
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}

    last_error: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for attempt in range(max_retries):
            try:
                current = url
                hops: list[str] = []
                for _ in range(max_redirects + 1):
                    assert_allowed_url(current, allowed_hosts, require_https=require_https)
                    with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchError(f"redirect without Location from {current}")
                            next_url = urljoin(current, location)
                            assert_allowed_url(next_url, allowed_hosts, require_https=require_https)
                            hops.append(next_url)
                            current = next_url
                            continue
                        if response.status_code in {408, 429} or response.status_code >= 500:
                            delay = backoff[min(attempt, len(backoff) - 1)]
                            if honor_retry_after:
                                delay = clamp_retry_after(response.headers.get("retry-after"), delay)
                            time.sleep(delay)
                            last_error = FetchError(f"retryable status {response.status_code}")
                            break
                        body = _stream_body_from_response(response, max_response_bytes)
                        content_type = response.headers.get("content-type", "application/octet-stream")
                        validate_fetch_payload(
                            requested_url=url,
                            final_url=current,
                            status_code=response.status_code,
                            content_type=content_type,
                            body=body,
                            allowed_hosts=allowed_hosts,
                            require_https=require_https,
                            max_response_bytes=max_response_bytes,
                            redirect_hops=tuple(hops),
                        )
                        result = FetchResult(
                            requested_url=url,
                            final_url=current,
                            status_code=response.status_code,
                            content_type=content_type,
                            body=body,
                            raw_sha256=sha256_bytes(body),
                            source_last_modified=response.headers.get("last-modified"),
                            from_cache=False,
                            redirect_hops=tuple(hops),
                        )
                        if cache_dir is not None:
                            save_raw_cache(cache_dir, result)
                        return result
                else:
                    raise FetchError(f"too many redirects for {url}")
            except (httpx.HTTPError, FetchError) as exc:
                last_error = exc
                if attempt + 1 < max_retries:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise FetchError(f"failed to fetch {url}: {last_error}")
