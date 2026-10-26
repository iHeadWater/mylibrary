from __future__ import annotations

import pytest

from hydrolitagent.scholars.errors import RosterError
from hydrolitagent.scholars.roster import load_roster, normalize_orcid


def test_csv_with_bom_and_chinese_headers(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text(
        "姓名,所属研究所,英文名/别名,ORCID,OpenAlexID,自查结论,补充说明\n"
        "张三,水利所,Zhang San|San Zhang,,A111|A222,无,备注\n",
        encoding="utf-8-sig",
    )
    roster = load_roster(path)
    person = roster.people[0]
    assert person.name == "张三"
    assert person.institute == "水利所"
    assert person.aliases == ("Zhang San", "San Zhang")
    assert person.openalex_ids == ("A111", "A222")
    assert person.self_check == "无"
    assert person.self_check_note == "备注"


def test_institute_alias(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text("姓名,所属机构\n张三,水利所\n", encoding="utf-8")
    roster = load_roster(path)
    assert roster.people[0].institute == "水利所"


def test_english_headers(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text("name,institute,aliases,orcid\nLi Si,Geotech,Li Si,\n", encoding="utf-8")
    roster = load_roster(path)
    assert roster.people[0].name == "Li Si"
    assert roster.people[0].institute == "Geotech"


def test_gb18030_encoding(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_bytes("姓名,所属研究所\n王五,水文所\n".encode("gb18030"))
    roster = load_roster(path)
    assert roster.people[0].name == "王五"


def test_missing_name_column_raises(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text("研究所,别名\n水利所,Zhang San\n", encoding="utf-8")
    with pytest.raises(RosterError, match="姓名"):
        load_roster(path)


def test_missing_name_value_raises_with_line(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text("姓名,所属研究所\n,水利所\n", encoding="utf-8")
    with pytest.raises(RosterError, match="第 2 行"):
        load_roster(path)


def test_toml_roster(tmp_path) -> None:
    path = tmp_path / "roster.toml"
    path.write_text(
        '[[people]]\nname = "张三"\ninstitute = "水利所"\naliases = ["Zhang San"]\n'
        'openalex_ids = ["A111"]\n',
        encoding="utf-8",
    )
    roster = load_roster(path)
    assert roster.people[0].aliases == ("Zhang San",)
    assert roster.people[0].openalex_ids == ("A111",)


def test_empty_roster_raises(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text("姓名,所属研究所\n", encoding="utf-8")
    with pytest.raises(RosterError, match="没有有效人员"):
        load_roster(path)


def test_unsupported_suffix(tmp_path) -> None:
    path = tmp_path / "roster.xlsx"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(RosterError, match="不支持"):
        load_roster(path)


def test_normalize_orcid() -> None:
    assert normalize_orcid("https://orcid.org/0000-0002-1825-0097") == "0000-0002-1825-0097"
    assert normalize_orcid("0000000218250097") == "0000-0002-1825-0097"


def test_invalid_orcid_raises(tmp_path) -> None:
    path = tmp_path / "roster.csv"
    path.write_text("姓名,ORCID\n张三,1234\n", encoding="utf-8")
    with pytest.raises(RosterError, match="ORCID"):
        load_roster(path)
