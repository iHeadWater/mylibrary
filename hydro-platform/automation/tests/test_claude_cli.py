import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import pytest
from test_card_draft import draft_case
from hydrolitagent.cards.card_draft import generate_subject_card_draft
from hydrolitagent.cards.card_generators.claude_cli import ClaudeCliAdapter, read_receipts
from hydrolitagent.cards.card_generators.single_agent import SingleAgentCardGeneratorAdapter
from hydrolitagent.cards.source_access import source_access_acceptable


def events(case):
    return [
      {"type":"assistant","message":{"content":[{"type":"tool_use","id":"read1","name":"Read",
          "input":{"file_path":str(case[2].pdf.resolve()),"pages":"1-12"}}]}},
      {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"read1","content":"PDF content"}]}},
      {"type":"result","subtype":"success","is_error":False,"structured_output":deepcopy(case[4]),"usage":{"input_tokens":10}},
    ]


def invoke(case, sequence, *, runner_error=None):
    app, record, _, _, _=case
    cfg=replace(app.card_generator, adapter="claude_cli", executable="claude", model="selected-model")
    runner=Mock(return_value=subprocess.CompletedProcess([],0,"\n".join(json.dumps(x) for x in sequence),""),
                side_effect=runner_error)
    provider=ClaudeCliAdapter(cfg, runner=runner, finder=lambda _:"claude.exe")
    result=generate_subject_card_draft(replace(app,card_generator=cfg),record,adapter=SingleAgentCardGeneratorAdapter(provider))
    return result, runner


def test_claude_uses_shared_draft_workflow_and_readonly_tools(draft_case):
    result, runner=invoke(draft_case,events(draft_case))
    assert result["ok"],result
    assert runner.call_count == 1
    command=runner.call_args.args[0]
    assert "--restricted" in command and "--safe-mode" in command and "--no-session-persistence" in command
    assert command[command.index("--tools")+1] == "Read"
    assert "--model" in command and "selected-model" in command
    draft=json.loads(Path(result["draft_path"]).read_text(encoding="utf-8"))
    assert draft["provenance"]["generation_protocol_version"] == "claude-local-pdf-v1"
    assert source_access_acceptable(draft["reading_record"])
    assert not draft["reading_record"]["full_read_verified"]


@pytest.mark.parametrize("kind",["missing_result","wrong_file","partial_pages","wrong_tool","failed_read","wrong_count","model_failure"])
def test_incomplete_or_forbidden_activity_never_becomes_a_draft(draft_case,kind):
    data=events(draft_case)
    block=data[0]["message"]["content"][0]
    if kind == "missing_result": data.pop(1)
    elif kind == "wrong_file": block["input"]["file_path"]="C:/other.pdf"
    elif kind == "partial_pages": block["input"]["pages"]="1-3"
    elif kind == "wrong_tool": block["name"]="Bash"
    elif kind == "failed_read": data[1]["message"]["content"][0]["is_error"]=True
    elif kind == "wrong_count": data[2]["structured_output"]["source_page_count"]=1
    else: data[2]["is_error"]=True
    result,_=invoke(draft_case,data)
    assert not result["ok"] and "draft_path" not in result


def test_forged_source_receipts_rejected(draft_case):
    result,_=invoke(draft_case,events(draft_case))
    draft=json.loads(Path(result["draft_path"]).read_text(encoding="utf-8"))
    draft["reading_record"]["pages_requested_successfully"]=[1]
    assert not source_access_acceptable(draft["reading_record"])


@pytest.mark.parametrize("malformed", [None, "bad", []])
def test_malformed_read_event_is_structured_failure(draft_case, malformed):
    data = events(draft_case)
    data[0]["message"] = malformed
    result, _ = invoke(draft_case, data)
    assert not result["ok"] and result["error"]["code"] == "CLAUDE_PDF_GENERATION_FAILED"


def test_smoke_implements_shared_adapter_interface(draft_case):
    cfg = replace(draft_case[0].card_generator, adapter="claude_cli")
    event = {"type":"result", "subtype":"success", "is_error":False, "result":"HYDRO_GENERATOR_OK"}
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(event), ""))
    adapter = ClaudeCliAdapter(cfg, runner=runner, finder=lambda _: "claude.exe")
    result = adapter.smoke_test()
    assert result["ok"] and result["model_invoked"]
    command = runner.call_args.args[0]
    assert command[command.index("--tools")+1] == ""


# ── 读取回执：不带 pages 的探测式读取 ──────────────────────────────────
# 探测式读取（Read 只给 file_path）不产生页覆盖。放行它是为了不让一次无害探测
# 中断流程，但它绝不能因此削弱任何既有校验：编号唯一性、页覆盖完整性、
# 失败回执的判定都必须保持原样。

def _read(source, ident, pages=None, *, receipt=True):
    """构造一次 Read 调用；pages=None 表示探测式读取，receipt=False 表示没有成功回执。"""
    block={"type":"tool_use","id":ident,"name":"Read","input":{"file_path":str(source)}}
    if pages is not None:
        block["input"]["pages"]=pages
    out=[{"type":"assistant","message":{"content":[block]}}]
    if receipt:
        out.append({"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":ident,"content":"PDF content"}]}})
    return out


def _terminal(case):
    return events(case)[2]


def test_pageless_probe_does_not_block_a_complete_read(draft_case):
    source=draft_case[2].pdf.resolve()
    result,_=invoke(draft_case, _read(source,"probe1")+events(draft_case))
    assert result["ok"],result
    draft=json.loads(Path(result["draft_path"]).read_text(encoding="utf-8"))
    assert draft["reading_record"]["pages_requested_successfully"]==list(range(1,13))


def test_pageless_probe_alone_never_counts_as_a_read(draft_case):
    source=draft_case[2].pdf.resolve()
    result,_=invoke(draft_case, _read(source,"probe1")+[_terminal(draft_case)])
    assert not result["ok"] and "draft_path" not in result


@pytest.mark.parametrize("kind",["partial","failed"])
def test_probe_does_not_relax_receipt_requirements(draft_case,kind):
    source=draft_case[2].pdf.resolve()
    read=_read(source,"read1","1-3")
    if kind=="failed":
        read[1]["message"]["content"][0]["is_error"]=True
    result,_=invoke(draft_case, _read(source,"probe1")+read+[_terminal(draft_case)])
    assert not result["ok"] and "draft_path" not in result


def test_duplicate_read_request_id_is_rejected(draft_case):
    """探测式读取的编号同样必须唯一，否则后续成功回执会借旧编号把未读页记成已读。"""
    source=draft_case[2].pdf.resolve()
    data=events(draft_case)[:2]+_read(source,"read1")+[_terminal(draft_case)]
    result,_=invoke(draft_case,data)
    assert not result["ok"] and "draft_path" not in result


def test_pageless_result_cannot_borrow_an_unread_requests_pages(draft_case):
    """请求一读了 1-12 页却没有成功回执；请求二不带页范围却复用同一编号。
    唯一成功的是请求二，它什么都没读到——因此不得判定 1-12 页已读。"""
    source=draft_case[2].pdf.resolve()
    data=_read(source,"r1","1-12",receipt=False)+_read(source,"r1")
    with pytest.raises(ValueError):
        read_receipts(data, source, 12)


@pytest.mark.parametrize("pages",["", "   ", None])
def test_blank_pages_is_treated_as_a_probe(draft_case, pages):
    source=draft_case[2].pdf.resolve()
    result,_=invoke(draft_case, _read(source,"probe1",pages)+events(draft_case))
    assert result["ok"],result


# ── 失败诊断：可行动且不泄露 ──────────────────────────────────────────

def test_read_failure_surfaces_the_models_own_read_report(draft_case):
    """模型已如实报告读不到时，其自报状态与证据应进入报错，否则根因会被页覆盖报错盖住。"""
    data=events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_status"]="UNREADABLE"
    data[-1]["structured_output"]["source_read_evidence"]="pdftoppm is not installed / Install poppler-utils"
    result,_=invoke(draft_case,data)
    assert not result["ok"]
    message=result["error"]["message"]
    assert "UNREADABLE" in message and "pdftoppm" in message


def test_diagnostic_text_is_bounded_and_single_line(draft_case):
    data=events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_evidence"]="x"*5000+"\n\tinjected"
    result,_=invoke(draft_case,data)
    message=result["error"]["message"]
    assert "x"*600 in message and "x"*601 not in message
    assert "\n" not in message and "\t" not in message


def test_failure_message_never_echoes_raw_cli_output(draft_case):
    """CLI 的 stderr 可能含本机认证设置，任何失败路径都不得把它带进结果。"""
    app,record,_,_,_=draft_case
    data=events(draft_case)
    data.pop(1)
    cfg=replace(app.card_generator,adapter="claude_cli",executable="claude")
    stdout="\n".join(json.dumps(x) for x in data)
    runner=Mock(return_value=subprocess.CompletedProcess([],0,stdout,"ANTHROPIC_AUTH_TOKEN=secret-value"))
    provider=ClaudeCliAdapter(cfg,runner=runner,finder=lambda _:"claude.exe")
    result=generate_subject_card_draft(replace(app,card_generator=cfg),record,
                                       adapter=SingleAgentCardGeneratorAdapter(provider))
    assert not result["ok"]
    assert "secret-value" not in json.dumps(result,ensure_ascii=False)


# ── 诊断脱敏：只隐凭据，不毁诊断 ──────────────────────────────────────
# 读取证据里合法包含源 PDF 的 sha256、页码与文件名。脱敏必须足够精确，
# 否则会把定位问题所需的信息一起屏蔽掉，比不脱敏更糟。

@pytest.mark.parametrize("secret",[
    "sk-ant-api03-AbCdEf1234567890",
    "Authorization: Bearer eyJhbGciOiJIUzI1",
    "ANTHROPIC_AUTH_TOKEN=super-secret-value",
    "ZOTERO_API_KEY=abcdef123456",
])
def test_credential_shaped_text_is_redacted(draft_case, secret):
    data = events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_evidence"] = secret
    result, _ = invoke(draft_case, data)
    assert "已隐去" in result["error"]["message"]
    assert secret not in result["error"]["message"]


@pytest.mark.parametrize("keep",[
    "SHA256 b95327448289ed46b1b886d89b4c28f694c985ee29191a229f0ea1893c259fa7",
    'Read(pages="1-9") 报错 pdftoppm is not installed',
    "the token: pdftoppm is missing",
    "page 1-17 of 17",
])
def test_technical_diagnostic_is_not_redacted(draft_case, keep):
    """sha256、工具名、页范围、不含 = 的散文都必须原样保留。"""
    data = events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_evidence"] = keep
    result, _ = invoke(draft_case, data)
    assert keep in result["error"]["message"]


def test_redaction_reaches_the_actual_failure_message(draft_case):
    data=events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_evidence"]="failed; ANTHROPIC_AUTH_TOKEN=leaked-value-here"
    result,_=invoke(draft_case,data)
    message=result["error"]["message"]
    assert "leaked-value-here" not in json.dumps(result,ensure_ascii=False)
    assert "已隐去" in message


@pytest.mark.parametrize("evidence", [
    'diagnostic: {"ANTHROPIC_AUTH_TOKEN": "private-test-credential"}',
    "diagnostic: API_KEY='private-test-credential with spaces'",
    'diagnostic: API_KEY=private-\x1b[31mtest-credential',
])
def test_read_failure_redacts_structured_and_terminal_credentials(draft_case, evidence):
    data = events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_evidence"] = evidence
    result, _ = invoke(draft_case, data)
    message = result["error"]["message"]
    assert not result["ok"] and "draft_path" not in result
    assert "private-" not in message
    assert "with spaces" not in message
    assert "\x1b" not in message
    assert "已隐去" in message


@pytest.mark.parametrize("error", [
    subprocess.TimeoutExpired(["claude", "--model", "private-command-value"], 5),
    OSError("private-command-value"),
    ValueError("private-command-value"),
])
def test_external_failure_does_not_echo_commands_or_unknown_exception_text(draft_case, error):
    result, runner = invoke(draft_case, [], runner_error=error)
    assert not result["ok"] and "draft_path" not in result
    assert runner.call_count == 1
    assert "private-command-value" not in json.dumps(result, ensure_ascii=False)
    assert result["error"]["code"] == "CLAUDE_PDF_GENERATION_FAILED"


@pytest.mark.parametrize("flag", ["false", "true", 0, 1, None, []])
def test_nonboolean_receipt_error_flag_never_counts_as_success(draft_case, flag):
    data = events(draft_case)
    data[1]["message"]["content"][0]["is_error"] = flag
    result, _ = invoke(draft_case, data)
    assert not result["ok"] and "draft_path" not in result


@pytest.mark.parametrize("ident", ["", " ", None, []])
def test_empty_or_nonstring_request_id_is_rejected(draft_case, ident):
    data = events(draft_case)
    data[0]["message"]["content"][0]["id"] = ident
    data[1]["message"]["content"][0]["tool_use_id"] = ident
    result, _ = invoke(draft_case, data)
    assert not result["ok"] and "draft_path" not in result


@pytest.mark.parametrize("status", ["private-status" * 1000, {"token": "private-status"}])
def test_invalid_model_status_is_not_echoed_or_allowed_to_hide_evidence(draft_case, status):
    data = events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_status"] = status
    data[-1]["structured_output"]["source_read_evidence"] = "pdftoppm is not installed"
    result, _ = invoke(draft_case, data)
    message = result["error"]["message"]
    assert "private-status" not in message
    assert "pdftoppm" in message and "INVALID" in message


@pytest.mark.parametrize("evidence", [
    "Command failed: pdftoppm -upw private-value source.pdf out",
    "Traceback (most recent call last): private-value",
    "```powershell\nclaude --model private-value\n```",
])
def test_model_diagnostic_does_not_relay_commands_or_raw_logs(draft_case, evidence):
    data = events(draft_case)
    data.pop(1)
    data[-1]["structured_output"]["source_read_evidence"] = evidence
    result, _ = invoke(draft_case, data)
    assert not result["ok"]
    message = result["error"]["message"]
    assert "private-value" not in message
    assert "成功 Read 回执" in message


def test_shared_prompt_does_not_mandate_findings_fields():
    """finding_id 是单篇流程独有的字段；共用提示词不得要求它，
    否则旧流程会被要求产出其 schema 中不存在的字段。"""
    shared=Path(__file__).resolve().parents[1]/"prompts/evidence-card-generation-v8.md"
    assert "finding_id" not in shared.read_text(encoding="utf-8")
    single=Path(__file__).resolve().parents[1]/"prompts/subject-card-draft-v1.md"
    assert "finding_id" in single.read_text(encoding="utf-8")
