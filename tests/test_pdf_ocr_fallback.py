"""OCR fallback, page provenance and region handling (#72).

The contract under test, in order of importance:

* a PDF that converts today still converts to the **same bytes** when the
  fallback is merely available -- recognition must never touch a page that has a
  text layer;
* a scanned page gets characters, its anchor records ``source="ocr"``, and the
  manifest records which engine and which settings produced them, because a
  recognised page is reproducible only for that engine and those settings;
* when a backend is missing or broken the failure is the old, readable
  ``CONVERTER_LOW_TEXT`` plus a reason -- never a silent downgrade;
* a quote found on a recognised page is evidence of what the card read, but it is
  reported separately and the reading is ``OCR_ASSISTED``, not ``VERIFIED``;
* text recognised inside a formula/table region is dropped and the region is kept
  as a picture, because noisy characters would otherwise pass every verbatim
  check and become "evidence".

Recognition and layout analysis are replaced by fakes here: these tests are about
the converter's decisions, not about model accuracy, and pinning a model's output
would make the suite fail on an upgrade. One test at the end uses the real
engine, and skips itself when the optional extra is absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import (
    WARNING_LAYOUT_UNAVAILABLE,
    WARNING_OCR_NO_HEADINGS,
    WARNING_OCR_PAGE,
    WARNING_REGION_REMOVED,
    PymupdfOcrConverter,
    lines_from_words,
)
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.domain.grounding import (
    audit_reading,
    expected_canaries,
    markdown_sha256,
)
from hydrolitagent.cards.domain.paper import MANIFEST_VERSION, PageAnchor, SourceIdentity
from hydrolitagent.cards.ports.paper import (
    ConversionOptions,
    ConversionRequest,
    ConverterDoctor,
    OcrOptions,
    RecognizedWord,
    RegionBox,
    RegionOptions,
)

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
OCR = OcrOptions(engine="fake", lang="ch", dpi=110, min_page_chars=40)
REGIONS = RegionOptions(enabled=True, backend="fake", text="remove")

BODY = (
    "Rainfall-runoff processes in small catchments are controlled by soil moisture, "
    "storm intensity and antecedent conditions. This study combines field observations "
    "with a simple bucket model to quantify those controls over three seasons and to "
    "separate the effect of storm intensity from the effect of antecedent wetness on "
    "the resulting peak discharge at the outlet of each instrumented catchment."
)


# -- fixtures -----------------------------------------------------------------------


def _text_pdf(path: Path, *, pages: int = 2) -> Path:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_textbox(
            pymupdf.Rect(72, 72, PAGE_WIDTH - 72, PAGE_HEIGHT - 72),
            BODY * 3,
            fontsize=11,
        )
    document.save(str(path))
    document.close()
    return path


def _scanned_pdf(path: Path, *, pages: int = 2, native_tail: bool = False) -> Path:
    """Pages that are pictures of text, plus optionally one real page."""

    source = pymupdf.open()
    page = source.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_textbox(
        pymupdf.Rect(72, 72, PAGE_WIDTH - 72, PAGE_HEIGHT - 72), BODY * 3, fontsize=11
    )
    pixmap = page.get_pixmap(dpi=110)

    document = pymupdf.open()
    for _ in range(pages):
        scanned = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        scanned.insert_image(scanned.rect, pixmap=pixmap)
    if native_tail:
        tail = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        tail.show_pdf_page(tail.rect, source, 0)
    document.save(str(path))
    document.close()
    source.close()
    return path


def _words(*lines: str, top: float = 100.0, height: float = 12.0) -> tuple[RecognizedWord, ...]:
    words: list[RecognizedWord] = []
    for row, text in enumerate(lines):
        left = 72.0
        for token in text.split():
            width = 8.0 * len(token)
            words.append(
                RecognizedWord(
                    text=token,
                    box=(left, top + row * 16, left + width, top + row * 16 + height),
                    confidence=0.9,
                )
            )
            left += width + 4
    return tuple(words)


class FakeRecognizer:
    engine_id = "fake"
    engine_version = "1.0"

    def __init__(self, words=None, *, error: str | None = None, available: bool = True):
        self.words = _words("Rainfall runoff in catchments", "is controlled by soil") if words is None else words
        self.error = error
        self._available = available
        self.calls = 0

    def available(self) -> ConverterDoctor:
        if not self._available:
            return ConverterDoctor(
                converter_id=self.engine_id,
                available=False,
                version=None,
                capabilities=(),
                error="后端未安装",
                fix="uv sync --extra ocr",
            )
        return ConverterDoctor(
            converter_id=self.engine_id,
            available=True,
            version=self.engine_version,
            capabilities=("words",),
        )

    def recognize(self, image_png, options):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.words


class FakeRegions:
    backend_id = "fake"
    backend_version = "2.0"

    def __init__(self, regions=None, *, available: bool = True, error: str | None = None):
        self.regions = regions if regions is not None else ()
        self.error = error
        self._available = available
        self.calls = 0

    def available(self) -> ConverterDoctor:
        if not self._available:
            return ConverterDoctor(
                converter_id=self.backend_id,
                available=False,
                version=None,
                capabilities=(),
                error="未安装",
                fix="uv sync --extra layout",
            )
        return ConverterDoctor(
            converter_id=self.backend_id,
            available=True,
            version=self.backend_version,
            capabilities=("formula", "table", "figure"),
        )

    def detect(self, pdf_path):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.regions


def _request(pdf: Path, output_dir: Path, options: ConversionOptions) -> ConversionRequest:
    return ConversionRequest(
        pdf_path=pdf,
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        size_bytes=pdf.stat().st_size,
        output_dir=output_dir,
        options=options,
    )


def _converter(*, ocr=OCR, regions=None, recognizer=None, detector=None):
    return PymupdfOcrConverter(
        ocr=ocr,
        regions=regions,
        recognizer=recognizer,
        region_detector=detector,
    )


def _convert(pdf, out, *, ocr=OCR, regions=None, recognizer=None, detector=None):
    options = ConversionOptions(ocr=ocr, regions=regions)
    return _converter(
        ocr=ocr, regions=regions, recognizer=recognizer, detector=detector
    ).convert(_request(pdf, out, options))


# -- the fallback -------------------------------------------------------------------


def test_scanned_document_is_recognised_and_recorded(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf")
    fake = FakeRecognizer()

    paper, error = _convert(pdf, tmp_path / "out", recognizer=fake)

    assert error is None
    assert fake.calls == 2, "one recognition per page without a text layer"
    assert paper.text_coverage == 1.0
    assert [anchor.source for anchor in paper.page_anchors] == ["ocr", "ocr"]
    assert paper.recognised_pages == (1, 2)
    assert paper.recognition is not None
    assert paper.recognition.engine == "fake"
    assert paper.recognition.version == "1.0"
    assert paper.recognition.dpi == OCR.dpi
    assert paper.recognition.pages == (1, 2)
    assert WARNING_OCR_PAGE in paper.warnings
    assert WARNING_OCR_NO_HEADINGS in paper.warnings
    markdown = paper.markdown_path.read_text(encoding="utf-8")
    assert "Rainfall runoff in catchments" in markdown
    manifest = json.loads(paper.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["recognition"]["pages"] == [1, 2]
    assert [anchor["source"] for anchor in manifest["page_anchors"]] == ["ocr", "ocr"]


def test_mixed_document_keeps_native_pages_native(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "mixed.pdf", pages=2, native_tail=True)
    fake = FakeRecognizer()

    paper, error = _convert(pdf, tmp_path / "out", recognizer=fake)

    assert error is None
    assert fake.calls == 2, "the page with a text layer must not be recognised"
    assert [anchor.source for anchor in paper.page_anchors] == ["ocr", "ocr", "native"]
    assert paper.recognition.pages == (1, 2)


def test_scope_all_recognises_every_page(tmp_path: Path):
    pdf = _text_pdf(tmp_path / "text.pdf")
    fake = FakeRecognizer()

    paper, error = _convert(
        pdf, tmp_path / "out", ocr=OcrOptions(engine="fake", dpi=110, scope="all"),
        recognizer=fake,
    )

    assert error is None
    assert fake.calls == 2
    assert {anchor.source for anchor in paper.page_anchors} == {"ocr"}


def test_recognised_page_is_not_harvested_for_figures(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    paper, error = _convert(pdf, tmp_path / "out", recognizer=FakeRecognizer())

    assert error is None
    assert paper.figures == ()
    assert not (tmp_path / "out" / "figures" / "page-001-figure-1.png").exists()


def test_native_document_is_byte_identical_with_the_fallback_enabled(tmp_path: Path):
    pdf = _text_pdf(tmp_path / "text.pdf")
    fake = FakeRecognizer()

    plain, _ = _convert(pdf, tmp_path / "plain", ocr=None)
    armed, error = _convert(pdf, tmp_path / "armed", recognizer=fake)

    assert error is None
    assert fake.calls == 0, "a readable document must never be rasterised"
    assert armed.markdown_sha256 == plain.markdown_sha256
    assert armed.markdown_path.read_bytes() == plain.markdown_path.read_bytes()
    assert {anchor.source for anchor in armed.page_anchors} == {"native"}
    assert armed.recognition is None


def test_missing_backend_degrades_to_the_old_error(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)

    paper, error = _convert(pdf, tmp_path / "off", ocr=None)
    assert paper is None
    assert error is not None and error.code == "CONVERTER_LOW_TEXT"

    paper, error = _convert(
        pdf, tmp_path / "unavailable", recognizer=FakeRecognizer(available=False)
    )
    assert paper is None
    assert error is not None and error.code == "CONVERTER_LOW_TEXT"
    assert "后端未安装" in error.message
    assert error.fix == "uv sync --extra ocr"


def test_broken_backend_is_reported_not_swallowed(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    paper, error = _convert(
        pdf, tmp_path / "out", recognizer=FakeRecognizer(error="onnxruntime 崩溃")
    )

    assert paper is None
    assert error is not None and error.code == "CONVERTER_OCR_FAILED"
    assert "第 1 页" in error.message


def test_empty_recognition_still_fails_closed(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    paper, error = _convert(pdf, tmp_path / "out", recognizer=FakeRecognizer(words=()))

    assert paper is None
    assert error is not None and error.code == "CONVERTER_LOW_TEXT"


def test_version_carries_the_recognition_settings():
    default = PymupdfOcrConverter(ocr=OcrOptions(engine="fake", dpi=300))
    denser = PymupdfOcrConverter(ocr=OcrOptions(engine="fake", dpi=220))

    assert default.converter_version.endswith("ocr.fake-ch-dpi300")
    assert denser.converter_version.endswith("ocr.fake-ch-dpi220")
    assert default.converter_version != denser.converter_version


# -- regions ------------------------------------------------------------------------


REGION_WORDS = _words(
    "the first prose line stays here",
    "the second prose line also stays",
    "formula line goes away",
    top=100,
)


def test_region_text_is_dropped_and_the_region_kept_as_a_picture(tmp_path: Path):
    """8b: unusable characters go, a picture of the formula stays."""

    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    words = REGION_WORDS
    # 框住第三行（y=132..144）
    region = RegionBox(page=1, kind="formula", box=(60.0, 130.0, 500.0, 146.0))
    detector = FakeRegions((region,))

    paper, error = _convert(
        pdf, tmp_path / "out", regions=REGIONS, recognizer=FakeRecognizer(words), detector=detector
    )

    assert error is None
    markdown = paper.markdown_path.read_text(encoding="utf-8")
    assert "the first prose line stays here" in markdown
    assert "formula line goes away" not in markdown
    assert "![Formula 1](figures/page-001-region-1.png)" in markdown
    assert (tmp_path / "out" / "figures" / "page-001-region-1.png").is_file()
    assert WARNING_REGION_REMOVED in paper.warnings
    manifest = json.loads(paper.manifest_path.read_text(encoding="utf-8"))
    assert manifest["regions"]["pages"] == [1]
    assert manifest["regions"]["removed_lines"] == 1
    assert manifest["regions"]["removed_chars"] > 0


def test_region_text_can_be_kept(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    words = REGION_WORDS
    region = RegionBox(page=1, kind="formula", box=(60.0, 130.0, 500.0, 146.0))
    keep = RegionOptions(enabled=True, backend="fake", text="keep")

    paper, error = _convert(
        pdf,
        tmp_path / "out",
        regions=keep,
        recognizer=FakeRecognizer(words),
        detector=FakeRegions((region,)),
    )

    assert error is None
    assert "formula line goes away" in paper.markdown_path.read_text(encoding="utf-8")
    assert WARNING_REGION_REMOVED not in paper.warnings


def test_a_line_only_touching_a_region_is_kept(tmp_path: Path):
    """The 70% rule: a paragraph that merely brushes a box must survive."""

    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    words = REGION_WORDS
    # 只覆盖第一行行尾一小块
    region = RegionBox(page=1, kind="table", box=(400.0, 99.0, 500.0, 113.0))

    paper, error = _convert(
        pdf, tmp_path / "out", regions=REGIONS,
        recognizer=FakeRecognizer(words), detector=FakeRegions((region,)),
    )

    assert error is None
    assert "the first prose line stays here" in paper.markdown_path.read_text(
        encoding="utf-8"
    )


def test_missing_layout_backend_only_warns(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)

    paper, error = _convert(
        pdf, tmp_path / "out", regions=REGIONS,
        recognizer=FakeRecognizer(), detector=FakeRegions(available=False),
    )

    assert error is None, "layout is a soft capability: text must still come out"
    assert WARNING_LAYOUT_UNAVAILABLE in paper.warnings
    assert "Rainfall runoff in catchments" in paper.markdown_path.read_text(encoding="utf-8")


def test_broken_layout_backend_only_warns(tmp_path: Path):
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)

    paper, error = _convert(
        pdf, tmp_path / "out", regions=REGIONS,
        recognizer=FakeRecognizer(), detector=FakeRegions(error="模型损坏"),
    )

    assert error is None
    assert WARNING_LAYOUT_UNAVAILABLE in paper.warnings


# -- word boxes to lines -------------------------------------------------------------


def test_lines_from_words_groups_rows_and_orders_left_to_right():
    words = (
        RecognizedWord("world", (120, 30, 160, 42)),
        RecognizedWord("hello", (72, 30, 110, 42)),
        RecognizedWord("second", (72, 50, 110, 62)),
    )
    assert [line.text for line in lines_from_words(words)] == ["hello world", "second"]


def test_lines_from_words_splits_columns_by_a_wide_gap():
    words = (
        RecognizedWord("left column text", (72, 100, 200, 112)),
        RecognizedWord("right column text", (320, 100, 450, 112)),
    )
    lines = lines_from_words(words)

    assert [line.text for line in lines] == ["left column text", "right column text"]
    assert lines[0].block != lines[1].block


def test_lines_from_words_splits_a_real_column_gutter():
    """The reported failure: a 17 pt gutter beside an 11 pt line stayed glued.

    Both items are whole lines because that is what the recogniser returns; the
    old threshold of two character heights kept them in one line, which joined
    one column's sentence to the other's and hid the gutter from the column
    detector as well.
    """

    words = (
        RecognizedWord(
            "Flooding is among the most devastating and costly natu-", (66, 391, 289, 401)
        ),
        RecognizedWord(
            "code the similarities and differences of various catchment", (306, 395, 545, 406)
        ),
    )

    lines = lines_from_words(words)

    assert [line.text for line in lines] == [
        "Flooding is among the most devastating and costly natu-",
        "code the similarities and differences of various catchment",
    ]


def test_lines_from_words_keeps_one_block_for_consecutive_body_lines():
    words = tuple(
        RecognizedWord(text, (72, 100 + row * 14, 172, 110 + row * 14))
        for row, text in enumerate(("first", "second", "third"))
    )
    assert len({line.block for line in lines_from_words(words)}) == 1


def test_lines_from_words_returns_nothing_for_no_words():
    assert lines_from_words(()) == ()


# -- roles -------------------------------------------------------------------------


def test_a_recognised_reference_page_is_classified_as_back_matter(tmp_path: Path):
    """Without headings, role keywords must still find "References"."""

    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    words = (
        RecognizedWord("References", (72, 90, 160, 104)),
        RecognizedWord("Smith", (72, 120, 100, 132)),
        RecognizedWord("Jones", (110, 120, 140, 132)),
    ) + _words("a reference entry that is long enough to look like prose", top=150)

    paper, error = _convert(pdf, tmp_path / "out", recognizer=FakeRecognizer(words))

    assert error is None
    assert paper.page_anchors[0].role == "references"


# -- cache --------------------------------------------------------------------------


def _cached(tmp_path: Path) -> tuple[PaperStore, Path, SourceIdentity]:
    pdf = _scanned_pdf(tmp_path / "scan.pdf", pages=1)
    paper, error = _convert(pdf, tmp_path / "out", recognizer=FakeRecognizer())
    assert error is None
    store = PaperStore(tmp_path)
    target = store.cache_dir / "papers" / paper.source.pdf_sha256 / (
        f"{paper.converter_id}-{paper.converter_version}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=True)
    for item in (tmp_path / "out").iterdir():
        if item.is_file():
            (target / item.name).write_bytes(item.read_bytes())
        else:
            (target / item.name).mkdir(exist_ok=True)
            for child in item.iterdir():
                (target / item.name / child.name).write_bytes(child.read_bytes())
    return store, target, paper.source


def test_cached_recognition_round_trips(tmp_path: Path):
    store, target, source = _cached(tmp_path)

    cached = store._load_cached(target, source)

    assert cached is not None
    assert cached.recognition is not None
    assert cached.recognition.engine == "fake"
    assert cached.page_anchors[0].source == "ocr"


def test_recognised_pages_without_provenance_are_not_trusted(tmp_path: Path):
    store, target, source = _cached(tmp_path)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("recognition")
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert store._load_cached(target, source) is None


def test_manifest_that_disagrees_with_its_anchors_is_rejected(tmp_path: Path):
    store, target, source = _cached(tmp_path)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["recognition"]["pages"] = [7]
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert store._load_cached(target, source) is None


def test_version_two_manifest_is_read_as_all_native(tmp_path: Path):
    store, target, source = _cached(tmp_path)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["manifest_version"] = 2
    manifest.pop("recognition")
    for anchor in manifest["page_anchors"]:
        anchor.pop("source")
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    cached = store._load_cached(target, source)

    assert cached is not None
    assert cached.recognition is None
    assert {anchor.source for anchor in cached.page_anchors} == {"native"}


# -- the reading status -------------------------------------------------------------

PAGE_ONE = "# Flood forecasting\n\n" + BODY
PAGE_TWO = "## Results\n\n" + BODY.replace("Rainfall", "Snowfall")


def _document(sources: tuple[str, ...]) -> tuple[str, tuple[PageAnchor, ...]]:
    canaries = ("c-0000000a", "c-0000000b")
    parts: list[str] = []
    anchors: list[PageAnchor] = []
    offset = 0
    for number, content in enumerate((PAGE_ONE, PAGE_TWO), start=1):
        header = f"<!-- page: {number} -->\n<!-- reading-canary: {canaries[number - 1]} -->\n"
        parts.append(header)
        offset += len(header)
        start = offset
        parts.append(content)
        offset += len(content)
        anchors.append(
            PageAnchor(
                page=number,
                char_start=start,
                char_end=start + len(content),
                heading=None,
                role="body",
                canary=canaries[number - 1],
                source=sources[number - 1],
            )
        )
        parts.append("\n")
        offset += 1
    return "".join(parts), tuple(anchors)


def _receipt(markdown: str) -> dict:
    return {
        "markdown_sha256": markdown_sha256(markdown),
        "read_mode": "file",
        "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
        "model_claimed_pages": [1, 2],
        "canaries_seen": list(expected_canaries(markdown)),
        "self_report": "fixture",
        "source_locations": [
            {
                "quote": BODY,
                "pdf_page": 1,
                "anchor": "P1",
                "section": None,
                "figure": None,
                "table": None,
            },
            {
                "quote": BODY.replace("Rainfall", "Snowfall"),
                "pdf_page": 2,
                "anchor": "P2",
                "section": None,
                "figure": None,
                "table": None,
            },
        ],
    }


def test_a_quote_on_a_recognised_page_makes_the_reading_ocr_assisted():
    markdown, anchors = _document(("native", "ocr"))

    audit = audit_reading(_receipt(markdown), markdown, anchors)

    assert audit.ok, audit.violations
    assert audit.reading.status == "OCR_ASSISTED"
    assert audit.reading.verified is False, "OCR_ASSISTED must not read as VERIFIED"
    assert audit.reading.accepted is True
    assert audit.reading.verified_pages == (1, 2)
    assert audit.reading.weak_quotes == 1
    assert audit.reading.weak_pages == (2,)
    payload = audit.reading.as_dict()
    assert payload["ocr_assisted"] is True
    assert payload["accepted"] is True


def test_a_native_reading_stays_verified():
    markdown, anchors = _document(("native", "native"))

    audit = audit_reading(_receipt(markdown), markdown, anchors)

    assert audit.ok
    assert audit.reading.status == "VERIFIED"
    assert audit.reading.weak_quotes == 0
    assert audit.reading.ocr_assisted is False


def test_ocr_pages_still_have_to_carry_the_quote():
    markdown, anchors = _document(("native", "ocr"))
    receipt = _receipt(markdown)
    receipt["source_locations"][1]["quote"] = "a sentence that is not in the paper at all"

    audit = audit_reading(receipt, markdown, anchors)

    assert not audit.ok
    assert audit.violations[0].code == "QUOTE_NOT_FOUND"


def test_versions_accept_an_ocr_assisted_reading_but_not_a_partial_one():
    from hydrolitagent.cards.application.card_version import _reading_accepted

    assert _reading_accepted({"reading_status": "VERIFIED"}) is True
    assert _reading_accepted({"reading_status": "OCR_ASSISTED"}) is True
    assert _reading_accepted({"reading_status": "PARTIAL"}) is False
    # Records written before #72 carry only the boolean.
    assert _reading_accepted({"reading_verified": True}) is True
    assert _reading_accepted({"reading_verified": False}) is False


def test_the_reading_layer_status_line_marks_recognised_pages():
    from hydrolitagent.cards.application.reading_layer import _status_line

    entry = {
        "status": "PASS",
        "production_eligible": True,
        "scientific_correctness_verified": False,
        "reading_verified_display": "否",
        "draft_id": "d-1",
        "ocr_assisted": True,
        "ocr_pages": [2, 3],
    }

    line = _status_line(entry)
    assert "第 2、3 页为 OCR 识别" in line
    assert "需对照扫描件复核" in line

    entry["ocr_assisted"] = False
    assert "OCR" not in _status_line(entry)


# -- doctor -------------------------------------------------------------------------


def test_doctor_reports_a_missing_helper_as_a_warning():
    from hydrolitagent.cards.application.doctor import helper_checks

    checks = helper_checks(
        FakeRecognizer(available=False).available(), capability="pdf.ocr", label="ocr"
    )

    assert len(checks) == 1
    assert checks[0].status == "warn"
    assert checks[0].capability == "pdf.ocr"
    assert checks[0].fix == "uv sync --extra ocr"


def test_doctor_is_silent_about_a_helper_that_is_not_configured():
    from hydrolitagent.cards.application.doctor import helper_checks

    assert helper_checks(None, capability="pdf.ocr", label="ocr") == ()


def test_converter_doctor_only_mentions_what_is_configured():
    plain = PymupdfOcrConverter()
    assert "ocr" not in plain.doctor().capabilities
    assert plain.doctor().recognizer is None

    armed = PymupdfOcrConverter(ocr=OcrOptions(), regions=RegionOptions())
    report = armed.doctor()
    assert "ocr" in report.capabilities
    assert "regions" in report.capabilities
    assert report.recognizer is not None


# -- the real engine ----------------------------------------------------------------


def test_rapidocr_adapter_reads_rendered_text():
    """One real call, so the adapter is not a fiction.

    Skipped when the optional extra is absent: the base install must stay
    dependency-free, and every other test here uses a fake.
    """

    pytest.importorskip("rapidocr_onnxruntime")
    from hydrolitagent.cards.adapters.ocr import recognizer_for

    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 140), "Compound flood modelling", fontsize=20)
    image = page.get_pixmap(dpi=200).tobytes("png")
    document.close()

    recognizer = recognizer_for("rapidocr")
    assert recognizer is not None
    report = recognizer.available()
    assert report.available, report.error

    words = recognizer.recognize(image, OcrOptions(engine="rapidocr", dpi=200))

    text = " ".join(word.text for word in words).lower()
    assert "compound" in text
    assert "flood" in text
