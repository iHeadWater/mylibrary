"""Contract tests against the REAL Zotero Desktop Local API.

Why this file exists
--------------------
Every other test for the Local API tools stubs ``httpx`` and invents the
response payload.  That is structurally unable to catch a wrong URL, a wrong
key type, or a payload shape the real endpoint never produces -- which is how
these defects survived a green suite:

  * the URL was missing the ``/api/users/0`` segment, so every call 404'd
  * ``/fulltext`` needs an *attachment* key, but the tools were documented as
    taking an item key
  * ``GET .../file`` returns a 302 to a ``file://`` URL -- for stored **and**
    linked attachments alike -- so ``zotero_get_file_info`` could never parse a
    response, and no size can ever be read from that route
  * an item can carry several PDFs (the paper plus press coverage of it), so
    picking the first child silently returns the wrong document

Nothing here is mocked: if the Local API answers, these exercise the real wire
format.  Skipped automatically when Zotero Desktop is not running.

Run explicitly::

    uv run pytest tests/test_zotero_local_api_integration.py -v
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import sys
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from hydrolitagent.zotero import server

# The server's default base is host.docker.internal, which only resolves inside
# a container -- on a bare host it raises "getaddrinfo failed".  These tests
# target the Local API on this machine, so they point at loopback unless the
# caller has deliberately configured somewhere else.
EXPLICIT_BASE = os.environ.get("ZOTERO_LOCAL_BASE_URL") or os.environ.get(
    "ZOTERO_LOCAL_API_URL"
)
LOCAL_BASE = EXPLICIT_BASE or "http://127.0.0.1:23119"
LOCAL_USER = "/api/users/0"
API = f"{LOCAL_BASE}{LOCAL_USER}"

# Any collection with PDF attachments will do; this is the one the survey used.
DISCOVERY_COLLECTION = "MLYBU9RM"

TIMEOUT = 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx responses instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_NO_REDIRECT = urllib.request.build_opener(_NoRedirect)


def _get(path: str) -> str:
    with urllib.request.urlopen(f"{API}{path}", timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _status_and_location(url: str) -> tuple[int, str]:
    """Like ``_status``, but a redirect is reported rather than followed."""
    try:
        with _NO_REDIRECT.open(url, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")


def _local_api_readiness() -> str:
    """Why the Local API is unusable, or ``""`` when it is ready.

    Probing the Connector route is not enough.  ``/connector/ping`` answers
    whenever Zotero is running, while every ``/api/*`` route stays ``403 Local
    API is not enabled`` until "Allow other applications on this computer to
    communicate with Zotero" is switched on.  Gating on the Connector route
    declared the API ready, then failed test by test on a 403 whose body already
    named the fix -- a green-looking suite that could not say what was wrong.
    """
    url = f"{LOCAL_BASE}{LOCAL_USER}/collections"
    try:
        with urllib.request.urlopen(url, timeout=3):
            return ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code == 403 and "not enabled" in body:
            return (
                "Zotero's Local API is disabled -- enable it via Settings -> "
                'Advanced -> "Allow other applications on this computer to '
                'communicate with Zotero"'
            )
        if exc.code == 400:
            return (
                f"Zotero rejected the Host header for {LOCAL_BASE} -- the Local "
                "API accepts only 127.0.0.1 / localhost as Host"
            )
        return f"Local API answered HTTP {exc.code} for {url}: {body[:120]}"
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        return f"Zotero Desktop not reachable at {LOCAL_BASE}: {exc}"


@pytest.fixture(scope="module", autouse=True)
def require_zotero_desktop():
    reason = _local_api_readiness()
    if reason:
        hint = ""
        if "host.docker.internal" in LOCAL_BASE:
            hint = (
                " -- note that host.docker.internal only resolves inside a "
                "container; on a bare host set "
                "ZOTERO_LOCAL_BASE_URL=http://127.0.0.1:23119"
            )
        pytest.skip(reason + hint)


@pytest.fixture(scope="module", autouse=True)
def restore_real_httpx():
    """Undo the unit tests' ``sys.modules`` stub if it landed first.

    ``test_zotero_server.py`` replaces ``sys.modules["httpx"]`` with a MagicMock
    before importing the server, and the module object is shared.  Depending on
    collection order that leaves ``server.httpx`` fake, which would make these
    tests silently assert against a mock.  Swapping the module global back is
    enough: the tools resolve ``httpx`` at call time.
    """
    original = server.httpx
    if isinstance(original, MagicMock):
        sys.modules.pop("httpx", None)
        import httpx as real_httpx

        server.httpx = real_httpx
        sys.modules["httpx"] = real_httpx
    yield
    server.httpx = original


@pytest.fixture(autouse=True)
def point_tools_at_loopback(monkeypatch):
    """Repoint the tools at loopback for the duration of each test.

    Applied per-test rather than by exporting an env var: this module shares
    the ``hydrolitagent.zotero.server`` module object with the stub-based unit
    tests, so anything done to it at import time leaks into them.
    """
    monkeypatch.setattr(server, "LOCAL_API_BASE", LOCAL_BASE)
    monkeypatch.setattr(server, "LOCAL_API_USER", LOCAL_USER)


def _pdf_children_of(item_key: str) -> list[dict]:
    rows = json.loads(_get(f"/items/{item_key}/children"))
    return [
        row.get("data", row)
        for row in rows
        if row.get("data", row).get("contentType") == "application/pdf"
    ]


def _fulltext_chars(attachment_key: str) -> int:
    try:
        payload = json.loads(_get(f"/items/{attachment_key}/fulltext"))
    except Exception:
        return -1
    return len(str(payload.get("content") or ""))


@pytest.fixture(scope="module")
def real_keys() -> tuple[str, str]:
    """A real ``(item_key, expected_pdf_key)`` pair.

    The expected key is the PDF child with the longest indexed fulltext,
    computed here straight from the Local API so the assertion stays
    independent of how the tool selects.  Item 6HF7ADML is the motivating
    case: five PDF children, and the paper (276,543 chars) is listed last.
    """
    items = json.loads(
        _get(f"/collections/{DISCOVERY_COLLECTION}/items/top?limit=10")
    )
    for item in items:
        item_key = item.get("key") or item.get("data", {}).get("key")
        if not item_key:
            continue
        try:
            pdfs = _pdf_children_of(item_key)
        except Exception:
            continue
        if not pdfs:
            continue
        scored = [
            (_fulltext_chars(str(entry.get("key") or "")), str(entry.get("key") or ""))
            for entry in pdfs
        ]
        best_chars, best_key = max(scored)
        if best_key and best_chars > 0:
            return item_key, best_key
    pytest.skip(f"no indexed PDF attachment found in {DISCOVERY_COLLECTION}")


# ── The route shapes themselves ───────────────────────────────────────────


def test_fulltext_requires_the_api_users_segment(real_keys):
    """Without /api/users/0 the route does not exist."""
    _, attachment_key = real_keys

    assert _status(f"{LOCAL_BASE}/items/{attachment_key}/fulltext") == 404
    assert _status(f"{API}/items/{attachment_key}/fulltext") == 200


def test_fulltext_requires_an_attachment_key(real_keys):
    """An item key 404s too -- which is why the tool resolves item keys
    through /children."""
    item_key, attachment_key = real_keys

    assert _status(f"{API}/items/{item_key}/fulltext") == 404
    assert _status(f"{API}/items/{attachment_key}/fulltext") == 200


def test_file_route_redirects_to_a_file_url(real_keys):
    """``GET .../file`` answers 302 with a ``file://`` Location.

    A client that calls ``.json()`` on it always fails, and because the body is
    never served there is no Content-Length to read either -- so file_info
    builds its answer from the item JSON plus ``/file/view/url`` instead.
    """
    _, attachment_key = real_keys

    status, location = _status_and_location(f"{API}/items/{attachment_key}/file")

    assert status == 302
    assert location.startswith("file://")


def test_view_url_route_returns_a_local_path(real_keys):
    """``/file/view/url`` is the route that actually yields a usable path."""
    _, attachment_key = real_keys

    body = _get(f"/items/{attachment_key}/file/view/url").strip()

    assert body.startswith("file:///")
    assert ".pdf" in body.lower()


def test_a_multi_pdf_item_really_does_have_a_longest_child(real_keys):
    """Guards the premise behind longest-wins selection.

    If this ever stops being true -- every child indexed equally -- the
    selection rule deserves re-examination rather than silent trust.
    """
    item_key, expected = real_keys

    pdfs = _pdf_children_of(item_key)
    assert len(pdfs) >= 2, "pick a collection item with several PDFs"

    scored = sorted(
        (_fulltext_chars(str(e.get("key") or "")), str(e.get("key") or ""))
        for e in pdfs
    )
    assert scored[-1][1] == expected
    assert scored[-1][0] > scored[0][0] * 2  # the spread is not marginal


# ── The tools, end to end, unmocked ───────────────────────────────────────


def test_get_fulltext_with_attachment_key(real_keys):
    _, attachment_key = real_keys

    result = json.loads(
        asyncio.run(server.zotero_get_fulltext(item_key=attachment_key))
    )

    assert "error" not in result, result
    assert len(result["content"]) > 1000
    assert result["attachmentKey"] == attachment_key


def test_get_fulltext_resolves_an_item_key_to_the_right_pdf(real_keys):
    """Passing a parent key must pick the paper, not the first PDF listed."""
    item_key, expected_pdf = real_keys

    result = json.loads(asyncio.run(server.zotero_get_fulltext(item_key=item_key)))

    assert "error" not in result, result
    assert result["attachmentKey"] == expected_pdf
    assert len(result["content"]) > 1000
    # The candidate list makes a wrong pick visible rather than silent.
    candidates = {c["key"]: c["chars"] for c in result["attachmentCandidates"]}
    assert candidates[expected_pdf] == max(candidates.values())


def test_get_file_info_matches_real_endpoint_fields(real_keys):
    """The returned keys must reflect what the endpoint really provides."""
    _, attachment_key = real_keys

    result = json.loads(
        asyncio.run(server.zotero_get_file_info(item_key=attachment_key))
    )

    assert "error" not in result, result
    assert result["contentType"] == "application/pdf"
    assert result["linkMode"] in {
        "linked_file",
        "linked_url",
        "imported_file",
        "imported_url",
    }
    # Always 0, by design: no Local API route reports a size.
    assert result["size"] == 0
    assert result["filename"]
    assert not result["filename"].startswith("attachments:")
    assert result["path"]


def test_get_file_info_resolves_an_item_key_to_the_right_pdf(real_keys):
    """file_info must describe the SAME pdf that get_fulltext would read."""
    item_key, expected_pdf = real_keys

    result = json.loads(
        asyncio.run(server.zotero_get_file_info(item_key=item_key))
    )

    assert "error" not in result, result
    assert result["attachmentKey"] == expected_pdf


def test_errors_do_not_leak_the_local_api_host():
    """Diagnostics name the path, not the configured host."""
    result = json.loads(
        asyncio.run(server.zotero_get_fulltext(item_key="ZZZZZZZZ"))
    )

    assert result["error"] is True
    assert LOCAL_BASE not in result["message"]
    assert "host.docker.internal" not in result["message"]
    assert "/api/users/0/items/ZZZZZZZZ/fulltext" in result["message"]


def test_a_malformed_key_is_rejected_before_any_request():
    result = json.loads(
        asyncio.run(server.zotero_get_fulltext(item_key="../../collections"))
    )

    assert result["error"] is True
    assert "well-formed" in result["message"]


# ── The Host rule the container override exists to satisfy ────────────────
#
# Asserted against the real server because it is *Zotero's* behaviour we depend
# on, not ours: if it ever stops being true, the override in
# ``server._local_api_headers()`` can be reconsidered instead of kept on faith.


def _status_with_host(path: str, host: str) -> int:
    """GET ``path`` on the Local API with an explicit ``Host`` header.

    ``urllib`` overwrites ``Host`` itself, so the request is written by hand.
    """
    conn = http.client.HTTPConnection("127.0.0.1", 23119, timeout=TIMEOUT)
    try:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1:23119", 200),
        ("localhost:23119", 200),
        # Not even other addresses in the loopback /8 are accepted.
        ("127.0.0.2:23119", 400),
        # What a container sends unless the header is overridden.
        ("host.docker.internal:23119", 400),
    ],
)
def test_only_a_loopback_host_header_is_accepted(host, expected):
    assert _status_with_host("/connector/ping", host) == expected
