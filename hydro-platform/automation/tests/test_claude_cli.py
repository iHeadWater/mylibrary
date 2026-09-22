import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import pytest
from test_card_draft import draft_case
from hydro_platform.card_draft import generate_subject_card_draft
from hydro_platform.card_generators.claude_cli import ClaudeCliAdapter, read_receipts
from hydro_platform.card_generators.single_agent import SingleAgentCardGeneratorAdapter
from hydro_platform.source_access import source_access_acceptable


def events(case):
    return [
      {"type":"assistant","message":{"content":[{"type":"tool_use","id":"read1","name":"Read",
          "input":{"file_path":str(case[2].pdf.resolve()),"pages":"1-12"}}]}},
      {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"read1","content":"PDF content"}]}},
      {"type":"result","subtype":"success","is_error":False,"structured_output":deepcopy(case[4]),"usage":{"input_tokens":10}},
    ]


def invoke(case, sequence):
    app, record, _, _, _=case
    cfg=replace(app.card_generator, adapter="claude_cli", executable="claude", model="selected-model")
    runner=Mock(return_value=subprocess.CompletedProcess([],0,"\n".join(json.dumps(x) for x in sequence),""))
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
