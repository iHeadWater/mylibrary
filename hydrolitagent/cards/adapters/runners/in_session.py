"""Two-phase runner for an agent the platform does not call.

``prepare`` stages exactly what a card task needs -- ``paper.md``, ``figures/``,
``request.json``, ``output.schema.json`` and a short README -- into a directory
the operator chooses. Any agent that can read files and write JSON can then
produce ``response.json``. ``finalize`` reads that file and checks the wire
contract before the ordinary grounding and draft path continues.

The platform never invokes a model here and never assumes the answer is true:
the Markdown digest, the integrity canaries and the JSON shape are all verified
in Python. A missing or altered ``response.json`` is a structured failure, not
an exception.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Mapping
from pathlib import Path

from hydrolitagent.cards.adapters.runners.workspace import (
    RESPONSE_FILENAME,
    SCHEMA_FILENAME,
    RunnerFailure,
    sha256_text,
)
from hydrolitagent.cards.domain.grounding import expected_canaries
from hydrolitagent.cards.domain.paper import (
    FIGURES_DIRNAME,
    MARKDOWN_FILENAME,
    FigureAsset,
    PreparedPaper,
)
from hydrolitagent.cards.ports.runner import (
    CardRunError,
    CardRunRequest,
    CardRunResult,
    RunnerDoctor,
)
from hydrolitagent.cards.ports.session import PreparedRun

RUN_REQUEST_FILENAME = "request.json"
INSTRUCTIONS_FILENAME = "README.md"

AWAITING_SESSION_OUTPUT = "AWAITING_SESSION_OUTPUT"

_INSTRUCTIONS = """\
# 待处理的制卡任务

这个目录由 `hydrolitagent cards run prepare` 生成。平台**不会**自动调用模型，
需要任意能读文件、写 JSON 的 agent 在这里完成一次阅读并写下答案。

## 要做的事

1. 完整阅读本目录的 `paper.md`（页锚点形如 `<!-- page: N -->`）。
2. 查看 `figures/` 中与卡片相关的图片；`request.json` 的 `figures` 给出页码与题注。
3. 按 `output.schema.json` 生成 JSON，写入同目录的 `{response}`。
4. 在 `reading_receipt.markdown_sha256` 回显 `request.json` 的 `markdown_sha256`。
5. 在 `reading_receipt.canaries_seen` 列出 `request.json` 的 `reading_canaries` 全部值。
6. 引文放在顶层 `source_locations`，必须是 `paper.md` 中的逐字原文。

## 约束

- 不要修改 `paper.md`；平台会用哈希复核。
- 不要假设平台读过论文：`verified` 只表示程序检查通过，不等于科学正确。
- 完成后由操作者执行：`uv run hydrolitagent cards run finalize --run-dir <本目录> --paper-input <输入 JSON> --json`

`request.json` 还包含 run_id、角色、页数、页锚点与图片清单，供 agent 参考。
"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


class InSessionRunner:
    """Stage files for an external agent and verify the answer it writes back."""

    runner_id = "in_session"

    def doctor(self) -> RunnerDoctor:
        return RunnerDoctor(
            runner_id=self.runner_id,
            available=True,
            detail="文件式两阶段协议，不需要外部程序或凭据；平台不调用模型",
        )

    # -- phase 1: stage -----------------------------------------------------------

    def prepare(self, request: CardRunRequest) -> PreparedRun:
        run_dir = Path(request.workspace)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RunnerFailure(
                "IN_SESSION_RUN_DIR_INVALID", f"无法创建运行目录：{exc}"
            ) from exc
        if not run_dir.is_dir():
            raise RunnerFailure(
                "IN_SESSION_RUN_DIR_INVALID", "run-dir 已被同名文件占用，无法写入"
            )

        if request.paper is None:
            return self._prepare_text(request, run_dir)

        source = Path(request.paper.markdown_path)
        if not source.is_file():
            raise RunnerFailure(
                "MARKDOWN_SOURCE_INVALID", "转换缓存中找不到 paper.md"
            )
        markdown = source.read_text(encoding="utf-8")
        if sha256_text(markdown) != request.paper.markdown_sha256:
            raise RunnerFailure(
                "MARKDOWN_SOURCE_INVALID", "转换缓存中的 paper.md 与摘要不一致"
            )

        markdown_path = run_dir / MARKDOWN_FILENAME
        shutil.copyfile(source, markdown_path)
        staged_markdown = markdown_path.read_text(encoding="utf-8")
        markdown_sha256 = sha256_text(staged_markdown)
        if markdown_sha256 != request.paper.markdown_sha256:
            raise RunnerFailure(
                "MARKDOWN_STAGE_SHA_MISMATCH",
                "写入运行目录后的 paper.md 与已转换论文摘要不一致",
            )

        figures_dir = run_dir / FIGURES_DIRNAME
        figures_dir.mkdir(parents=True, exist_ok=True)
        figures: list[FigureAsset] = []
        for figure in request.paper.figures:
            if not figure.path.is_file():
                raise RunnerFailure(
                    "FIGURE_ASSET_MISSING",
                    f"转换缓存缺少图片：{figure.figure_id}",
                )
            target = figures_dir / figure.path.name
            shutil.copyfile(figure.path, target)
            if _sha256_file(target) != _sha256_file(figure.path):
                raise RunnerFailure(
                    "FIGURE_STAGE_MISMATCH", f"图片复制后校验失败：{figure.figure_id}"
                )
            figures.append(
                FigureAsset(
                    page=figure.page,
                    figure_id=figure.figure_id,
                    path=target,
                    caption=figure.caption,
                )
            )

        canaries = expected_canaries(staged_markdown)
        schema_path = run_dir / SCHEMA_FILENAME
        _write_text(
            schema_path,
            json.dumps(request.output_schema, ensure_ascii=False, indent=2) + "\n",
        )

        request_path = run_dir / RUN_REQUEST_FILENAME
        payload = {
            "schema_version": 1,
            "runner_id": self.runner_id,
            "run_id": request.run_id,
            "role": request.role,
            "markdown_file": MARKDOWN_FILENAME,
            "markdown_sha256": markdown_sha256,
            "source_pdf_sha256": request.paper.source.pdf_sha256,
            "page_count": request.paper.page_count,
            "converter_id": request.paper.converter_id,
            "converter_version": request.paper.converter_version,
            "reading_mode": request.reading_mode,
            "reading_canaries": list(canaries),
            "page_anchors": [
                {"page": anchor.page, "role": anchor.role, "heading": anchor.heading}
                for anchor in request.paper.page_anchors
            ],
            # Same data under the name the hand-off contract uses: a short
            # outline an agent can use to plan a long read.
            "outline": [
                {"page": anchor.page, "heading": anchor.heading, "role": anchor.role}
                for anchor in request.paper.page_anchors
                if anchor.heading
            ],
            "figures": [
                {
                    "figure_id": figure.figure_id,
                    "page": figure.page,
                    "file": f"{FIGURES_DIRNAME}/{figure.path.name}",
                    "caption": figure.caption,
                }
                for figure in figures
            ],
            "output_schema_file": SCHEMA_FILENAME,
            "response_file": RESPONSE_FILENAME,
            "prompt": request.prompt,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "timeout_seconds": request.timeout_seconds,
        }
        _write_text(
            request_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

        instructions_path = run_dir / INSTRUCTIONS_FILENAME
        _write_text(instructions_path, _INSTRUCTIONS.format(response=RESPONSE_FILENAME))

        return PreparedRun(
            run_dir=run_dir,
            markdown_path=markdown_path,
            markdown_sha256=markdown_sha256,
            request_path=request_path,
            schema_path=schema_path,
            instructions_path=instructions_path,
            response_path=run_dir / RESPONSE_FILENAME,
            page_count=request.paper.page_count,
            canaries=canaries,
            figures=tuple(figures),
        )

    def _prepare_text(self, request: CardRunRequest, run_dir: Path) -> PreparedRun:
        """Stage a synthesis task: the prompt is the material, there is no paper."""

        schema_path = run_dir / SCHEMA_FILENAME
        _write_text(
            schema_path,
            json.dumps(request.output_schema, ensure_ascii=False, indent=2) + "\n",
        )
        request_path = run_dir / RUN_REQUEST_FILENAME
        payload = {
            "schema_version": 1,
            "runner_id": self.runner_id,
            "run_id": request.run_id,
            "role": request.role,
            "mode": "text_only",
            "output_schema_file": SCHEMA_FILENAME,
            "response_file": RESPONSE_FILENAME,
            "prompt": request.prompt,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "timeout_seconds": request.timeout_seconds,
        }
        _write_text(
            request_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        instructions_path = run_dir / INSTRUCTIONS_FILENAME
        _write_text(
            instructions_path,
            "# 待处理的文本任务\n\n"
            "这个目录没有 `paper.md`：材料在 `request.json` 的 `prompt` 中。\n"
            "按 `output.schema.json` 生成 JSON，写入同目录的 "
            f"`{RESPONSE_FILENAME}`。平台不会自动调用模型。\n",
        )
        return PreparedRun(
            run_dir=run_dir,
            # A text task stages no paper: the path is named but not written,
            # the digest is empty and the counts are zero.
            markdown_path=run_dir / MARKDOWN_FILENAME,
            markdown_sha256="",
            request_path=request_path,
            schema_path=schema_path,
            instructions_path=instructions_path,
            response_path=run_dir / RESPONSE_FILENAME,
            page_count=0,
            canaries=(),
            figures=(),
        )

    # -- phase 2: collect ---------------------------------------------------------

    def finalize(
        self, run_dir: Path, *, paper: PreparedPaper | None
    ) -> CardRunResult:
        started = time.monotonic()
        directory = Path(run_dir)
        try:
            markdown = None
            if paper is not None:
                markdown_path = directory / MARKDOWN_FILENAME
                if not markdown_path.is_file():
                    raise RunnerFailure(
                        "IN_SESSION_RUN_DIR_INVALID", "运行目录缺少 paper.md"
                    )
                markdown = markdown_path.read_text(encoding="utf-8")
                if sha256_text(markdown) != paper.markdown_sha256:
                    raise RunnerFailure(
                        "MARKDOWN_CHANGED", "运行目录中的 paper.md 已改变，拒绝接受输出"
                    )

            response_path = directory / RESPONSE_FILENAME
            if not response_path.is_file():
                raise RunnerFailure(
                    "IN_SESSION_RESPONSE_MISSING",
                    f"还没有 {RESPONSE_FILENAME}；任意 agent 写完后再执行 finalize",
                )
            try:
                payload = json.loads(response_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RunnerFailure(
                    "IN_SESSION_RESPONSE_INVALID", f"{RESPONSE_FILENAME} 不是有效 JSON"
                ) from exc
            if not isinstance(payload, Mapping):
                raise RunnerFailure(
                    "IN_SESSION_RESPONSE_INVALID", f"{RESPONSE_FILENAME} 必须是 JSON 对象"
                )

            if paper is None:
                # Text-only task: there is no reading to verify, only a JSON
                # answer. Grounding belongs to the caller's own checks.
                return CardRunResult(
                    runner_id=self.runner_id,
                    ok=True,
                    output=dict(payload),
                    model_invoked=False,
                    duration_seconds=round(time.monotonic() - started, 2),
                    unvalidated_output_path=str(response_path),
                )

            receipt = payload.get("reading_receipt")
            if not isinstance(receipt, Mapping):
                raise RunnerFailure(
                    "IN_SESSION_READING_RECEIPT_MISSING",
                    "答案缺少 reading_receipt 块",
                )
            claimed = receipt.get("markdown_sha256")
            if not isinstance(claimed, str) or not claimed.strip():
                raise RunnerFailure(
                    "IN_SESSION_MARKDOWN_SHA_MISSING",
                    "reading_receipt 必须回显 markdown_sha256",
                )
            if claimed.strip().casefold() != paper.markdown_sha256.casefold():
                raise RunnerFailure(
                    "MARKDOWN_SHA_MISMATCH",
                    "reading_receipt 的 markdown_sha256 与 prepared paper 不一致",
                    detail={"expected": paper.markdown_sha256},
                )

            # ``paper`` is not None here, so ``markdown`` is the staged text.
            expected = expected_canaries(markdown)
            seen = receipt.get("canaries_seen")
            seen_values = (
                {item.strip() for item in seen if isinstance(item, str)}
                if isinstance(seen, list)
                else set()
            )
            missing = [canary for canary in expected if canary not in seen_values]
            if missing:
                raise RunnerFailure(
                    "IN_SESSION_CANARY_MISSING",
                    "reading_receipt.canaries_seen 缺少完整性 canary",
                    detail={"missing": missing, "expected": list(expected)},
                )

            return CardRunResult(
                runner_id=self.runner_id,
                ok=True,
                output=dict(payload),
                model_invoked=False,
                duration_seconds=round(time.monotonic() - started, 2),
                unvalidated_output_path=str(response_path),
            )
        except RunnerFailure as exc:
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=CardRunError(
                    code=exc.code, message=str(exc), detail=exc.detail or None
                ),
                model_invoked=False,
                duration_seconds=round(time.monotonic() - started, 2),
            )
        except (OSError, ValueError, TypeError) as exc:
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=CardRunError(
                    "IN_SESSION_IO_ERROR",
                    f"读取运行目录失败（{type(exc).__name__}）",
                ),
                model_invoked=False,
                duration_seconds=round(time.monotonic() - started, 2),
            )

    # -- CardRunner ---------------------------------------------------------------

    def run(self, request: CardRunRequest) -> CardRunResult:
        """Finalize an existing answer, or report that none was written yet."""

        started = time.monotonic()
        run_dir = Path(request.workspace)
        if not (run_dir / RESPONSE_FILENAME).is_file():
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=CardRunError(
                    code=AWAITING_SESSION_OUTPUT,
                    message=(
                        "in_session 运行器不调用模型；请让 agent 读取运行目录并写入 "
                        f"{RESPONSE_FILENAME} 后执行 cards run finalize"
                    ),
                ),
                model_invoked=False,
                duration_seconds=round(time.monotonic() - started, 2),
            )
        return self.finalize(run_dir, paper=request.paper)


__all__ = [
    "AWAITING_SESSION_OUTPUT",
    "INSTRUCTIONS_FILENAME",
    "InSessionRunner",
    "RUN_REQUEST_FILENAME",
]
