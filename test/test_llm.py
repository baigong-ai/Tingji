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


def test_summarize_short(cfg_api):
    with mock.patch("app.llm._chat", return_value="## 核心议题\n...") as m:
        out = llm.summarize("short text", cfg_api)
    assert m.call_count == 1
    assert "核心议题" in out


def test_summarize_long_map_reduce(cfg_api):
    long_md = "x" * 9000
    with mock.patch("app.llm._chat", return_value="partial") as m:
        llm.summarize(long_md, cfg_api)
    assert m.call_count >= 2
