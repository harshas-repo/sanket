"""HTTP plumbing shared by every source adapter.

Government portals in Nepal are slow, occasionally TLS-broken and sometimes only
reachable over plain HTTP. This module makes those realities explicit instead of
papering over them: every call returns a typed result, and an unreachable source
is reported as unreachable - never substituted with sample data.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("sanket.http")

USER_AGENT = (
    "SanketDisasterIntelligence/1.0 (+national disaster response platform; "
    "read-only official data ingestion)"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/html, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}


class SourceUnavailable(Exception):
    """Raised when a source could not be reached at all. Distinct from
    'reachable but returned nothing' so health status stays honest."""

    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


class SourceMalformed(Exception):
    """Reached the source but the payload did not look like the expected shape."""

    def __init__(self, url: str, reason: str, sample: str = ""):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason
        self.sample = sample[:400]


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    elapsed_ms: int
    content_type: str = ""
    attempts: int = 1
    headers: dict[str, str] = field(default_factory=dict)
    encoding: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400


def fetch(
    url: str,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
    verify_tls: bool = True,
    retries: int = 2,
    retry_statuses: tuple[int, ...] = (),
    max_bytes: int | None = None,
) -> FetchResult:
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    # These headers are not decoration: several official endpoints answer 406 to a
    # generic client, so a per-adapter header set that is not attached is a per-adapter
    # header set that does not exist.
    client_headers = {key: value for key, value in merged.items() if value}

    last_error: Exception | None = None
    last_result: FetchResult | None = None
    for attempt in range(1, retries + 2):
        started = time.perf_counter()
        try:
            with httpx.Client(
                timeout=timeout,
                verify=verify_tls,
                follow_redirects=True,
                headers=client_headers,
                limits=httpx.Limits(max_keepalive_connections=2),
            ) as client:
                response = client.request(method, url, data=data, json=json_body, params=params)
            elapsed = int((time.perf_counter() - started) * 1000)
            text = _decode(response)
            if max_bytes and len(text) > max_bytes:
                # Keep the tail for inline-JSON pages? No - truncate defensively and
                # let the adapter decide; callers that expect huge pages set max_bytes.
                text = text[:max_bytes]
            last_result = FetchResult(
                url=str(response.url),
                status_code=response.status_code,
                text=text,
                elapsed_ms=elapsed,
                content_type=response.headers.get("content-type", ""),
                attempts=attempt,
                headers=dict(response.headers),
                encoding=response.encoding or "",
            )
            # Some government portals answer 500 intermittently under load (the DRR
            # register does). Retrying a server error is different from retrying a
            # transport failure, so it is opt-in per adapter.
            if last_result.status_code in retry_statuses and attempt <= retries:
                sleep_for = min(8.0, (2 ** (attempt - 1)) + random.random())
                logger.warning(
                    "fetch %s -> HTTP %s, retry in %.1fs", url, last_result.status_code, sleep_for
                )
                time.sleep(sleep_for)
                continue
            return last_result
        except Exception as exc:  # network/DNS/TLS/timeout
            last_error = exc
            if attempt <= retries:
                sleep_for = min(8.0, (2 ** (attempt - 1)) + random.random())
                logger.warning("fetch %s failed (%s), retry in %.1fs", url, exc, sleep_for)
                time.sleep(sleep_for)

    if last_result is not None:
        return last_result
    raise SourceUnavailable(url, f"{type(last_error).__name__}: {last_error}")


_LATIN_CHARSETS = {"iso-8859-1", "latin-1", "latin1", "windows-1252", "cp1252", "ascii", "us-ascii"}


def _decode(response: httpx.Response) -> str:
    """Nepali official pages often omit or mislabel the charset as ISO-8859-1, and
    decoding Devanagari that way writes permanent mojibake into the database.

    Heuristic: trust a declared non-Latin charset; but when the server declares a
    single-byte Latin charset (or none), try strict UTF-8 first, since a Latin-1
    decode never fails and would silently win.
    """
    content = response.content
    declared = (response.encoding or "").lower()
    if declared and declared not in _LATIN_CHARSETS:
        try:
            return content.decode(declared)
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for name in (*([declared] if declared else []), "windows-1252", "latin-1"):
        try:
            return content.decode(name)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def fetch_json(url: str, **kwargs: Any) -> Any:
    import json

    result = fetch(url, **kwargs)
    if not result.ok:
        raise SourceMalformed(url, f"HTTP {result.status_code}", result.text)
    try:
        return json.loads(_strip_php_noise(result.text))
    except ValueError as exc:
        raise SourceMalformed(url, f"invalid JSON ({exc})", result.text) from exc


_LEADING_ERROR_BLOCKS = (
    "<div style=\"border:1px solid #990000\"",
    "<h4>A PHP Error was encountered</h4>",
)


def _strip_php_noise(text: str) -> str:
    """CodeIgniter on drrportal.gov.np prepends PHP notices *inside* JSON responses.

    Verified live during source inspection: even the JSON endpoints come back as
    `<div ...><h4>A PHP Error...</h4></div>[{...}]`. We trim everything before the
    first real JSON token rather than pretending the payload was clean.
    """
    stripped = text.lstrip()
    first_obj = stripped.find("{")
    first_arr = stripped.find("[")
    candidates = [i for i in (first_obj, first_arr) if i >= 0]
    if not candidates:
        return stripped
    idx = min(candidates)
    if stripped[:idx].count("<div") or stripped[:idx].count("<h4"):
        return stripped[idx:]
    return stripped


def inline_json_array(page: str, variable: str) -> str | None:
    """Extract `const <variable> = [ ... ];` from a server-rendered page.

    Used by sources that embed their data inline instead of exposing an endpoint
    (seismonepal.gov.np earthquake map, DHM river-watch gauges).
    """
    marker = None
    for pattern in (f"const {variable}", f"var {variable}", f"let {variable}", f"{variable} ="):
        pos = page.find(pattern)
        if pos != -1:
            marker = pos
            break
    if marker is None:
        return None
    start = None
    for i in range(marker, len(page)):
        if page[i] in "[{":
            start = i
            break
    if start is None:
        return None
    opener = page[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(page)):
        ch = page[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = not in_string
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return page[start : i + 1]
    return None
