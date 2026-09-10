"""Tests for scripts/fetch_collection_fulltext.py.

The script's job grew a second half: it used to fetch every PDF's full text
only to decide which was longest, then discard the losers.  This library has
items carrying five PDFs -- the paper plus press coverage of it -- and the
discarded ones include things a human would want (e.g. the published version
alongside the preprint).  Every attachment's text is now kept on disk; the
MCP tool still returns a single paper, because inlining several would blow up
the caller's context.

The Zotero client and the full-text fetch are both stubbed; nothing here
touches the network or the developer's real library.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "fetch_collection_fulltext.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "fetch_collection_fulltext_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


# ── Fixtures ──────────────────────────────────────────────────────────────

ITEM_KEY = "ITEM0001"
SLUG = "lovelace_test_paper"
PDFS = ["ATT00001", "ATT00002", "ATT00003"]
# Deliberately not in listing order: the longest must win regardless of order.
TEXTS = {
    "ATT00001": "short. " * 10,
    "ATT00002": "medium. " * 100,
    "ATT00003": "longest. " * 1000,
}
LONGEST = "ATT00003"


def _item(key: str = ITEM_KEY) -> dict:
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "journalArticle",
            "title": "A Test Paper on Zotero Plumbing",
            "date": "2024",
            "DOI": "10.1000/test",
            "publicationTitle": "Test Journal",
            "dateAdded": "2024-01-01T00:00:00Z",
            "creators": [{"firstName": "Ada", "lastName": "Lovelace"}],
            "path": "attachments:paper.pdf",
        },
    }


def _pdf_child(key: str) -> dict:
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "attachment",
            "contentType": "application/pdf",
        },
    }


class FakeZot:
    """Stands in for pyzotero.Zotero, recording what was asked of it."""

    def __init__(self, items: dict, children: dict):
        self._items = items
        self._children = children
        self.item_calls: list[str] = []
        self.children_calls: list[str] = []

    def item(self, key: str) -> dict:
        self.item_calls.append(key)
        return self._items[key]

    def children(self, key: str) -> list[dict]:
        self.children_calls.append(key)
        return self._children.get(key, [])


@pytest.fixture
def fake_zot() -> FakeZot:
    return FakeZot(
        items={ITEM_KEY: _item()},
        children={ITEM_KEY: [_pdf_child(k) for k in PDFS]},
    )


@pytest.fixture
def env(monkeypatch):
    """Credential-shaped env plus a stubbed .env loader."""
    monkeypatch.setenv("ZOTERO_API_KEY", "test-key")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "12345")
    monkeypatch.setattr(script, "_load_env", lambda: False)


def _run(fake: FakeZot, argv: list[str], texts=None, side_effect=None):
    """Invoke the CLI with a fake pyzotero install and a stubbed fetch."""
    pyzotero_stub = types.ModuleType("pyzotero")
    pyzotero_stub.zotero = types.SimpleNamespace(Zotero=lambda *a, **k: fake)

    if side_effect is not None:
        fetch = patch.object(script, "_fetch_fulltext", side_effect=side_effect)
    else:
        table = texts if texts is not None else TEXTS
        fetch = patch.object(
            script, "_fetch_fulltext", side_effect=lambda key: (table[key], 1)
        )

    with fetch, patch.dict(sys.modules, {"pyzotero": pyzotero_stub}):
        return script.main(argv)


def _base_argv(tmp_path: Path) -> list[str]:
    return [
        "fetch",
        "--keys",
        ITEM_KEY,
        "--out-dir",
        str(tmp_path),
        "--slug",
        f"{ITEM_KEY}={SLUG}",
    ]


# ── Every PDF is kept ─────────────────────────────────────────────────────


def test_every_pdf_text_is_written_to_disk(tmp_path, fake_zot, env):
    """The losers used to be discarded after the length comparison."""
    assert _run(fake_zot, _base_argv(tmp_path)) == 0

    for key in PDFS:
        path = tmp_path / SLUG / f"{key}.txt"
        assert path.exists(), f"missing {path}"
        assert path.read_text(encoding="utf-8") == TEXTS[key]


def test_selected_text_file_holds_the_longest(tmp_path, fake_zot, env):
    """`{slug}.txt` is unchanged, so existing chunks and cards stay valid."""
    assert _run(fake_zot, _base_argv(tmp_path)) == 0

    assert (tmp_path / f"{SLUG}.txt").read_text(encoding="utf-8") == TEXTS[LONGEST]


def test_json_result_is_unchanged_by_the_new_output(tmp_path, fake_zot, env):
    assert _run(fake_zot, _base_argv(tmp_path)) == 0

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))

    assert payload["result"] == TEXTS[LONGEST]
    assert payload["attachmentKey"] == LONGEST
    # pre-existing shapes must survive
    assert payload["attachmentCandidates"][0]["key"] == PDFS[0]


def test_attachments_index_describes_every_pdf(tmp_path, fake_zot, env):
    assert _run(fake_zot, _base_argv(tmp_path)) == 0

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    attachments = payload["attachments"]

    assert [a["key"] for a in attachments] == PDFS
    assert [a["chars"] for a in attachments] == [len(TEXTS[k]) for k in PDFS]
    assert [a["selected"] for a in attachments].count(True) == 1
    assert next(a for a in attachments if a["selected"])["key"] == LONGEST
    for entry in attachments:
        assert entry["textFile"] == f"{SLUG}/{entry['key']}.txt"


def test_single_pdf_item_writes_one_text_and_fetches_once(tmp_path, env):
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={ITEM_KEY: [_pdf_child("ONLY0001")]},
    )
    texts = {"ONLY0001": "the only paper. " * 50}
    fetched_keys: list[str] = []

    def fetch(key: str):
        fetched_keys.append(key)
        return texts[key], 1

    assert _run(fake, _base_argv(tmp_path), side_effect=fetch) == 0
    # The name says "fetches once" -- so count them.
    assert fetched_keys == ["ONLY0001"]

    assert (tmp_path / SLUG / "ONLY0001.txt").read_text(encoding="utf-8") == texts["ONLY0001"]
    assert sorted(p.name for p in (tmp_path / SLUG).iterdir()) == ["ONLY0001.txt"]
    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert payload["attachments"] == [
        {
            "key": "ONLY0001",
            "chars": len(texts["ONLY0001"]),
            "pages": 1,
            "textFile": f"{SLUG}/ONLY0001.txt",
            "selected": True,
        }
    ]


def test_non_pdf_children_are_ignored(tmp_path, env):
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={
            ITEM_KEY: [
                {"key": "LINKEDURL", "data": {"key": "LINKEDURL", "itemType": "attachment"}},
                _pdf_child("ONLY0001"),
            ]
        },
    )

    assert _run(fake, _base_argv(tmp_path), texts={"ONLY0001": "x" * 100}) == 0

    assert sorted(p.name for p in (tmp_path / SLUG).iterdir()) == ["ONLY0001.txt"]


# ── Failure handling ──────────────────────────────────────────────────────


def test_total_failure_exits_nonzero_and_omits_the_fallback_key(
    tmp_path, fake_zot, env, monkeypatch
):
    """The fallback key's presence must mean "a local PDF is available"."""
    # Collection order can pull the repo .env in via another test module, which
    # would set GDRIVE_PAPERS_PATH for the whole process; clear it so this
    # asserts the code path rather than whatever is on the developer's disk.
    monkeypatch.delenv("GDRIVE_PAPERS_PATH", raising=False)

    assert _run(fake_zot, _base_argv(tmp_path), side_effect=RuntimeError("boom")) == 3

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert payload["result"] == ""
    assert payload["source"] == "unavailable"
    assert "gdriveFallback" not in payload
    assert not (tmp_path / f"{SLUG}.txt").exists()
    assert not (tmp_path / SLUG).exists()


def test_partial_failure_still_writes_what_worked(tmp_path, env):
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={ITEM_KEY: [_pdf_child(k) for k in PDFS]},
    )

    def flaky(key: str):
        if key == "ATT00002":
            raise RuntimeError("boom")
        return TEXTS[key], 1

    assert _run(fake, _base_argv(tmp_path), side_effect=flaky) == 0

    assert (tmp_path / SLUG / "ATT00001.txt").exists()
    assert not (tmp_path / SLUG / "ATT00002.txt").exists()
    assert (tmp_path / SLUG / "ATT00003.txt").exists()
    assert (tmp_path / f"{SLUG}.txt").read_text(encoding="utf-8") == TEXTS[LONGEST]

    # The failed one is still listed, with no textFile and no content.
    index = {
        a["key"]: a
        for a in json.loads(
            (tmp_path / f"{SLUG}.json").read_text(encoding="utf-8")
        )["attachments"]
    }
    assert index["ATT00002"] == {
        "key": "ATT00002",
        "chars": 0,
        "pages": 0,
        "textFile": None,
        "selected": False,
    }


def test_a_failed_rerun_does_not_destroy_the_previous_artifacts(tmp_path, env):
    """A run that gets nothing must leave the last good files alone.

    Pruning {slug}/ and then writing nothing would delete a previous run's
    texts while {slug}.txt still held a paper -- the same contamination the
    pruning exists to prevent, one file over.  The JSON still records the
    failure (that is what gdriveFallback is for), and its index points at no
    file, so a consumer following the index never reads the stale ones.
    """
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={ITEM_KEY: [_pdf_child(k) for k in PDFS]},
    )
    argv = _base_argv(tmp_path) + ["--force"]

    assert _run(fake, argv) == 0
    before_txt = (tmp_path / f"{SLUG}.txt").read_text(encoding="utf-8")
    before_files = sorted(p.name for p in (tmp_path / SLUG).iterdir())

    assert _run(fake, argv, side_effect=RuntimeError("boom")) == 3

    assert (tmp_path / f"{SLUG}.txt").read_text(encoding="utf-8") == before_txt
    assert sorted(p.name for p in (tmp_path / SLUG).iterdir()) == before_files

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert payload["source"] == "unavailable"
    # The index is the authoritative pointer, and this run wrote nothing.
    assert all(a["textFile"] is None for a in payload["attachments"])


def test_a_rerun_drops_files_for_attachments_that_went_away(tmp_path, fake_zot, env):
    """{slug}/ describes the CURRENT attachments, so a stale file must go.

    Otherwise a consumer told to read every file in the directory would read a
    PDF that is no longer attached -- the very contamination this feature
    exists to make visible.
    """
    stale = tmp_path / SLUG
    stale.mkdir(parents=True)
    (stale / "GONE0001.txt").write_text("from a previous run", encoding="utf-8")

    assert _run(fake_zot, _base_argv(tmp_path)) == 0

    assert not (stale / "GONE0001.txt").exists()
    assert sorted(p.name for p in stale.iterdir()) == sorted(
        f"{k}.txt" for k in PDFS
    )


def test_all_empty_text_reports_zero_pages(tmp_path, env):
    """Matches the pre-rewrite behaviour: no text at all means totalPages 0.

    The old code seeded its comparison with an empty string, so an item whose
    PDFs all yield nothing left `best_pages` at its initial 0.  Seeding the
    comparison with -1 instead would latch the first attachment's page count,
    breaking the "result/totalPages unchanged" invariant.
    """
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={ITEM_KEY: [_pdf_child(k) for k in PDFS]},
    )

    assert _run(fake, _base_argv(tmp_path), side_effect=lambda k: ("", 7)) == 3

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert payload["result"] == ""
    assert payload["totalPages"] == 0
    assert not (tmp_path / f"{SLUG}.txt").exists()
    assert all(a["chars"] == 0 for a in payload["attachments"])
    assert all(a["textFile"] is None for a in payload["attachments"])
    # The first attachment stays the nominated one, exactly as before the
    # rewrite (best_att defaulted to attachments[0]).
    assert payload["attachmentKey"] == PDFS[0]
    assert [a["key"] for a in payload["attachments"] if a["selected"]] == [PDFS[0]]


def test_gdrive_fallback_is_emitted_when_the_pdf_is_on_disk(tmp_path, env, monkeypatch):
    """The counterpart to the omission test: it must still fire when it can."""
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "paper.pdf").write_text("x", encoding="utf-8")
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", str(papers))
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={
            ITEM_KEY: [
                {
                    "key": "ATT00001",
                    "data": {
                        "key": "ATT00001",
                        "itemType": "attachment",
                        "contentType": "application/pdf",
                        "path": "attachments:paper.pdf",
                    },
                }
            ]
        },
    )

    assert _run(fake, _base_argv(tmp_path), side_effect=RuntimeError("boom")) == 3

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert payload["gdriveFallback"] == str(papers / "paper.pdf")


# ── Path guards ───────────────────────────────────────────────────────────


def test_slug_override_rejects_a_path(tmp_path, fake_zot, env):
    argv = _base_argv(tmp_path)[:-1] + [f"{ITEM_KEY}=../evil"]

    assert _run(fake_zot, argv) == 1
    assert not (tmp_path.parent / "evil.json").exists()
    assert not (tmp_path.parent / "evil").exists()


@pytest.mark.parametrize(
    "bad", ["../evil", "a/b", "a\\b", "C:/x", "~/x", "..", "", "a\x00b"]
)
def test_bare_filename_rejects_paths(bad):
    assert script._is_bare_filename(bad) is False


@pytest.mark.parametrize(
    "hostile_key",
    ["../../../pwned", "..\\..\\pwned", "/abs/pwned", "C:/pwned", "SUB/../../out"],
)
def test_a_forged_attachment_key_cannot_escape_the_output_dir(
    tmp_path, env, hostile_key
):
    """The attachment key becomes a filename, so it needs the slug's guard.

    Without it the key is joined straight onto the output directory: a value
    carrying separators writes outside --out-dir and records that path in the
    JSON.  `_is_bare_filename` was unit-tested on its own, but this call site
    was not, so removing it from the loop kept every test green.
    """
    fake = FakeZot(
        items={ITEM_KEY: _item()},
        children={ITEM_KEY: [_pdf_child(hostile_key)]},
    )

    assert _run(fake, _base_argv(tmp_path), texts={hostile_key: "x" * 100}) == 0

    payload = json.loads((tmp_path / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert payload["attachments"][0]["textFile"] is None
    # Nothing may appear outside the requested output directory.
    assert not (tmp_path.parent / "pwned.txt").exists()
    assert not (tmp_path.parent / "out.txt").exists()
    assert not (tmp_path / SLUG).exists()


@pytest.mark.parametrize("good", ["paper.pdf", "Lu 等 - 2024 - x.pdf", "a_b-c.txt"])
def test_bare_filename_accepts_plain_names(good):
    assert script._is_bare_filename(good) is True


def test_gdrive_fallback_resolves_a_plain_name(tmp_path, monkeypatch):
    (tmp_path / "paper.pdf").write_text("x", encoding="utf-8")
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", str(tmp_path))

    assert script._gdrive_fallback({"path": "attachments:paper.pdf"}) == str(
        tmp_path / "paper.pdf"
    )


@pytest.mark.parametrize(
    "hostile",
    [
        "attachments:C:/Windows/win.ini",
        "attachments:../../secret.pdf",
        "attachments:/etc/passwd",
        "attachments:~/x.pdf",
    ],
)
def test_gdrive_fallback_refuses_to_escape_its_base(tmp_path, monkeypatch, hostile):
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", str(tmp_path))

    assert script._gdrive_fallback({"path": hostile}) is None


def test_gdrive_fallback_ignores_non_linked_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("GDRIVE_PAPERS_PATH", str(tmp_path))

    assert script._gdrive_fallback({"path": "storage:paper.pdf"}) is None
    assert script._gdrive_fallback({}) is None
