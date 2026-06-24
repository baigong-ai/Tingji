from unittest import mock

import pytest

from app import llm
from app.config import APIConfig, OllamaConfig, LLMConfig


@pytest.fixture
def cfg_api():
    return LLMConfig(
        mode="api",
        api=APIConfig(base_url="http://x", api_key="k", model="gpt"),
        ollama=OllamaConfig(base_url="", model="", api_key=""),
        polish_chunk_minutes=6,
        temperature=0.3,
        max_retries=2,
    )


def test_chunk_sentences_by_minutes(cfg_api):
    sentences = [
        {"text": "a", "start": 0, "end": 1000, "spk": 0},
        {"text": "b", "start": 1000, "end": 5*60*1000, "spk": 0},
        {"text": "c", "start": 7*60*1000, "end": 13*60*1000, "spk": 1},
    ]
    chunks = llm.chunk_sentences(sentences, minutes=6)
    assert len(chunks) == 2
    assert chunks[0][0]["text"] == "a"
    assert chunks[1][-1]["text"] == "c"


def test_format_chunk(cfg_api):
    chunk = [
        {"text": "hello", "start": 0, "end": 1000, "spk": 0},
        {"text": "world", "start": 1000, "end": 2000, "spk": 1},
    ]
    out = llm.format_chunk(chunk)
    assert "说话人 0" in out
    assert "hello" in out
    assert "说话人 1" in out
    assert "world" in out


def test_polish_calls_chat_per_chunk(cfg_api):
    sentences = [
        {"text": "hi", "start": 0, "end": 1000, "spk": 0},
    ]
    with mock.patch("app.llm._chat", return_value="## 说话人 0\nhi") as m:
        md = llm.polish(sentences, cfg_api)
    assert m.call_count == 1
    assert "## 说话人 0" in md


def test_polish_fallback_on_failure(cfg_api):
    sentences = [
        {"text": "hi", "start": 0, "end": 1000, "spk": 0},
    ]
    with mock.patch("app.llm._chat", side_effect=Exception("boom")):
        md = llm.polish(sentences, cfg_api)
    assert "[整理失败]" in md
    assert "hi" in md


def test_summarize_short_returns_structured(cfg_api):
    raw = '{"summary":"概述","decisions":["d1"],"action_items":["a1"],"open_questions":["q1"]}'
    with mock.patch("app.llm._chat", return_value=raw) as m:
        out = llm.summarize("short text", cfg_api)
    assert m.call_count == 1
    assert m.call_args.kwargs.get("json_mode") is True
    assert isinstance(out, dict)
    assert out["summary"] == "概述"
    assert out["decisions"] == ["d1"]
    assert out["action_items"] == ["a1"]


def test_summarize_fallback_on_bad_json(cfg_api):
    with mock.patch("app.llm._chat", return_value="这不是 JSON，就是一段普通总结"):
        out = llm.summarize("short text", cfg_api)
    assert isinstance(out, str)
    assert "普通总结" in out


def test_summarize_long_map_reduce_merges(cfg_api):
    long_md = "x" * 9000
    raw = '{"summary":"s","decisions":["d"],"action_items":[],"open_questions":[]}'
    with mock.patch("app.llm._chat", return_value=raw) as m:
        out = llm.summarize(long_md, cfg_api)
    assert m.call_count >= 2
    assert isinstance(out, dict)


def test_summary_to_md(cfg_api):
    md = llm.summary_to_md({"summary": "s", "decisions": ["d"], "action_items": ["a"], "open_questions": []})
    assert "## 概述" in md and "s" in md
    assert "## 决议" in md and "- d" in md
    assert "## 待办" in md and "- [ ] a" in md
    assert "待讨论" not in md


def test_polish_injects_template_hint(cfg_api):
    sentences = [{"text": "hi", "start": 0, "end": 1000, "spk": 0}]
    with mock.patch("app.llm._chat", return_value="## 说话人 0\nhi") as m:
        llm.polish(sentences, cfg_api, template_hint="侧重决议与待办")
    assert "侧重决议与待办" in m.call_args.args[0]


def test_summarize_injects_template_hint(cfg_api):
    raw = '{"summary":"s","decisions":[],"action_items":[],"open_questions":[]}'
    with mock.patch("app.llm._chat", return_value=raw) as m:
        llm.summarize("short", cfg_api, template_hint="侧重访谈主题")
    assert "侧重访谈主题" in m.call_args.args[0]


def test_template_prompt_block(cfg_api):
    tpl = {"background": "周会", "terms": "K8s、灰度", "direction": "进展", "content": "", "framework": ""}
    block = llm.template_prompt_block(tpl)
    assert "会议背景：周会" in block
    assert "K8s、灰度" in block
    assert "总结方向：进展" in block
    assert "总结内容" not in block
    assert llm.template_prompt_block({}) == ""


def test_polish_injects_meeting_context(cfg_api):
    sentences = [{"text": "hi", "start": 0, "end": 1000, "spk": 0}]
    with mock.patch("app.llm._chat", return_value="## 说话人 0\nhi") as m:
        llm.polish(sentences, cfg_api, meeting_context="K8s 灰度发布")
    assert "K8s 灰度发布" in m.call_args.args[0]


def test_summarize_injects_meeting_context(cfg_api):
    with mock.patch("app.llm._chat", return_value="## 核心议题\nx") as m:
        llm.summarize("short", cfg_api, meeting_context="K8s 灰度发布")
    assert "K8s 灰度发布" in m.call_args.args[0]


def test_summarize_omits_context_when_empty(cfg_api):
    with mock.patch("app.llm._chat", return_value="## 核心议题\nx") as m:
        llm.summarize("short", cfg_api)
    assert "会议背景" not in m.call_args.args[0]
