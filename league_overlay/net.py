"""HTTP helpers. Local Riot ports skip TLS verification and proxies."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

USER_AGENT = "LeagueOverlay/1.0"
_local_opener: urllib.request.OpenerDirector | None = None


def local_opener() -> urllib.request.OpenerDirector:
    global _local_opener
    if _local_opener is None:
        context = ssl._create_unverified_context()
        _local_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
        )
    return _local_opener


def local_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 0.6,
) -> tuple[int | None, object | None, str]:
    """GET JSON from a localhost Riot API.

    Returns (status, body, error). error is "" on a clean HTTP response,
    "down" when nothing is listening, or "badjson" when the body is not JSON.
    Connection failures are normal when League is closed.
    """
    request = urllib.request.Request(
        url,
        headers=headers or {"Accept": "application/json"},
    )
    try:
        with local_opener().open(request, timeout=timeout) as response:
            raw = response.read()
            code = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        return int(exc.code), None, ""
    except Exception:
        return None, None, "down"
    if not raw:
        return code, None, ""
    try:
        return code, json.loads(raw.decode("utf-8")), ""
    except json.JSONDecodeError:
        return code, None, "badjson"


def public_bytes(url: str, timeout: float = 20) -> bytes:
    """Download a public Data Dragon file with normal TLS verification."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()
