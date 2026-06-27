from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from .models import SheetData


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def col_to_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    col = 0
    for ch in match.group(1):
        col = col * 26 + ord(ch) - ord("A") + 1
    return col - 1


def shared_strings(zf: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in root.findall("main:si", NS):
        strings.append("".join(t.text or "" for t in si.findall(".//main:t", NS)))
    return strings


def cell_value(cell: ET.Element, strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("main:v", NS)
    if cell_type == "s" and value is not None and value.text is not None:
        idx = int(value.text)
        return strings[idx] if 0 <= idx < len(strings) else ""
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//main:t", NS)).strip()
    return (value.text if value is not None and value.text is not None else "").strip()


def workbook_sheets(path: Path) -> Iterable[tuple[str, str]]:
    with ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        for sheet in workbook.find("main:sheets", NS):
            name = sheet.attrib["name"]
            rid = sheet.attrib[f"{{{NS['rel']}}}id"]
            target = relmap[rid].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            yield name, target


def read_workbook(path: Path) -> list[SheetData]:
    sheets: list[SheetData] = []
    with ZipFile(path) as zf:
        strings = shared_strings(zf)
        for name, target in workbook_sheets(path):
            root = ET.fromstring(zf.read(target))
            row_map: dict[int, dict[int, str]] = {}
            max_col = 0
            for row in root.findall(".//main:sheetData/main:row", NS):
                row_idx = int(row.attrib.get("r", len(row_map) + 1))
                row_cells: dict[int, str] = {}
                for cell in row.findall("main:c", NS):
                    col_idx = col_to_index(cell.attrib.get("r", ""))
                    max_col = max(max_col, col_idx)
                    row_cells[col_idx] = cell_value(cell, strings)
                row_map[row_idx] = row_cells
            rows = [[row_map[row_idx].get(i, "") for i in range(max_col + 1)] for row_idx in sorted(row_map)]
            sheets.append(SheetData(path.name, name, rows))
    return sheets


def clean_filename(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("_")


def export_sheets(sheets: list[SheetData], output_dir: Path) -> list[dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for sheet in sheets:
        base = clean_filename(f"{Path(sheet.workbook).stem}__{sheet.sheet}")
        csv_path = output_dir / f"{base}.csv"
        json_path = output_dir / f"{base}.json"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(sheet.rows)
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(sheet.rows, f, ensure_ascii=False, indent=2)
        manifest.append(
            {
                "workbook": sheet.workbook,
                "sheet": sheet.sheet,
                "rows": str(len(sheet.rows)),
                "csv": str(csv_path),
                "json": str(json_path),
            }
        )
    return manifest
