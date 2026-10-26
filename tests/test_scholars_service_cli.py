from __future__ import annotations

import json

from hydrolitagent.scholars import cli
from hydrolitagent.scholars.models import PersonQuery, WorksFetch
from hydrolitagent.scholars.service import run_batch

from scholars_fixtures import author_payload, work_payload


class FakeClient:
    def __init__(self, *, works=None, authors=None) -> None:
        self.works = works or [work_payload("W1")]
        self.authors = authors or {"A1": author_payload("A1", name="Zhang San")}
        self.closed = False

    def get_author(self, author_id):
        return self.authors[author_id]

    def search_authors(self, *args, **kwargs):
        return []

    def find_authors_by_orcid(self, orcid):
        return []

    def fetch_works(self, author_ids, **kwargs):
        return WorksFetch(
            works=tuple(self.works),
            total_count=len(self.works),
            pages=1,
            request_count=1,
        )

    def get_work(self, work_id):
        return self.works[0]

    def close(self):
        self.closed = True


def test_run_batch_isolates_chinese_only_failure(tmp_path) -> None:
    queries = [
        PersonQuery(
            name="张三",
            aliases=("Zhang San",),
            openalex_ids=("A1",),
            index=1,
        ),
        PersonQuery(name="测试无别名", index=2),
    ]
    batch = run_batch(queries, cli._load_config(cli._parser().parse_args(["batch", "--roster", "x.csv"])), client=FakeClient())
    assert batch.people[0].status == "ok"
    assert batch.people[0].stats.paper_count == 1
    assert batch.people[1].status == "failed"
    assert batch.ok is False


def test_cli_stats_json_and_files(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "make_client", lambda *args, **kwargs: FakeClient())
    code = cli.main(
        [
            "stats",
            "--name",
            "张三",
            "--name-en",
            "Zhang San",
            "--openalex-id",
            "A1",
            "--output-dir",
            str(tmp_path),
            "--json",
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert code == 0
    assert payload["ok"] is True
    assert (tmp_path / "form_summary.csv").is_file()
    assert (tmp_path / "summary.json").is_file()


def test_cli_batch_partial_exit_code(tmp_path, monkeypatch, capsys) -> None:
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "姓名,所属研究所,英文名/别名,OpenAlexID\n张三,水利所,Zhang San,A1\n测试无别名,测试所,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "make_client", lambda *args, **kwargs: FakeClient())
    code = cli.main(
        [
            "batch",
            "--roster",
            str(roster),
            "--output-dir",
            str(tmp_path / "out"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert payload["totals"]["people"] == 2
    assert (tmp_path / "out" / "form_summary.csv").is_file()


def test_cli_resolve_json(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "make_client", lambda *args, **kwargs: FakeClient())
    code = cli.main(
        [
            "resolve",
            "--name",
            "张三",
            "--name-en",
            "Zhang San",
            "--openalex-id",
            "A1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["identity"]["status"] == "resolved"


def test_cli_config_error_exit_2(capsys) -> None:
    code = cli.main(["stats", "--name", "张三", "--config", "does-not-exist.toml", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"]["code"] == "CONFIG_ERROR"
