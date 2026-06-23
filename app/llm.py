import logging
import re

from openai import OpenAI

from app.config import LLMConfig

log = logging.getLogger(__name__)

POLISH_PROMPT = """你是一个会议录音整理助手。下面是一段会议的逐句转录（按时间顺序，已标注说话人）。
请整理成规范的会议记录：

规则：
- 保留说话人分段，使用 `## 说话人 N` 作为小标题
- 去除口头禅（那个、然后、嗯、就是、然后然后）和重复词
- 理顺句子结构，使其通顺
- 不要合并不同说话人的内容
- 不要添加未出现的信息
- 同一说话人连续多句可合并为一个或几个完整段落

转录内容：
{input}
"""

SUMMARIZE_PROMPT = """下面是一份整理后的会议记录。请输出会议纪要，格式：

## 核心议题
（列出讨论的主要话题，每条一行）

## 决议
（已确定的事项，每条一行）

## 待办
（用 `- [ ]` 列表，每项后括注负责人）

会议记录：
{input}
"""

REDUCE_PROMPT = """下面是同一会议的多个分段摘要，请合并为一份统一的会议纪要（核心议题 / 决议 / 待办）：

{input}
"""


def _client(cfg: LLMConfig) -> OpenAI:
    if cfg.mode == "api":
        return OpenAI(base_url=cfg.api.base_url, api_key=cfg.api.api_key)
    return OpenAI(base_url=cfg.ollama.base_url, api_key=cfg.ollama.api_key)


def _model_name(cfg: LLMConfig) -> str:
    return cfg.api.model if cfg.mode == "api" else cfg.ollama.model


def _clean_response(text: str) -> str:
    """Strip <think>...</think> reasoning blocks emitted by some models."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _chat(prompt: str, cfg: LLMConfig) -> str:
    client = _client(cfg)
    resp = client.chat.completions.create(
        model=_model_name(cfg),
        messages=[{"role": "user", "content": prompt}],
        temperature=cfg.temperature,
    )
    return _clean_response(resp.choices[0].message.content or "")


def test_connection(cfg: LLMConfig) -> tuple[bool, str]:
    try:
        reply = _chat("用中文说你好", cfg)
        return True, reply
    except Exception as e:
        return False, str(e)


def chunk_sentences(sentences: list[dict], minutes: int) -> list[list[dict]]:
    if not sentences:
        return []
    chunk_ms = minutes * 60 * 1000
    chunks = []
    current = [sentences[0]]
    bucket_start = sentences[0]["start"]
    for s in sentences[1:]:
        if s["start"] - bucket_start >= chunk_ms:
            chunks.append(current)
            current = [s]
            bucket_start = s["start"]
        else:
            current.append(s)
    chunks.append(current)
    return chunks


def format_chunk(chunk: list[dict], mark_failed: bool = False) -> str:
    lines = []
    last_spk = None
    tag = " [整理失败]" if mark_failed else ""
    for s in chunk:
        spk = s["spk"]
        if spk != last_spk:
            lines.append(f"\n## 说话人 {spk}{tag}")
            last_spk = spk
        lines.append(s["text"])
    return "\n".join(lines).strip()


def polish(sentences: list[dict], cfg: LLMConfig, on_log=None) -> str:
    def _log(level, msg):
        if on_log:
            try:
                on_log(level, msg)
            except Exception:
                pass
    chunks = chunk_sentences(sentences, cfg.polish_chunk_minutes)
    _log("info", f"整理: 共 {len(chunks)} 段, 模型 {_model_name(cfg)}")
    outputs = []
    for i, chunk in enumerate(chunks):
        _log("info", f"整理第 {i+1}/{len(chunks)} 段 ...")
        prompt = POLISH_PROMPT.format(input=format_chunk(chunk))
        success = False
        for _ in range(cfg.max_retries + 1):
            try:
                outputs.append(_chat(prompt, cfg))
                success = True
                break
            except Exception as e:
                log.warning("polish chunk failed: %s", e)
        if not success:
            _log("warn", f"第 {i+1} 段整理失败, 保留原文")
            outputs.append(format_chunk(chunk, mark_failed=True))
    _log("info", "整理完成")
    return "\n\n---\n\n".join(outputs)


def _split_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def summarize(processed_md: str, cfg: LLMConfig, on_log=None) -> str:
    def _log(level, msg):
        if on_log:
            try:
                on_log(level, msg)
            except Exception:
                pass
    if len(processed_md) < 8000:
        _log("info", f"生成总结, 模型 {_model_name(cfg)}")
        r = _chat(SUMMARIZE_PROMPT.format(input=processed_md), cfg)
        _log("info", "总结完成")
        return r
    chunks = _split_text(processed_md, 6000)
    _log("info", f"总结: 长文 map-reduce, 切 {len(chunks)} 块")
    partials = []
    for c in chunks:
        partials.append(_chat(SUMMARIZE_PROMPT.format(input=c), cfg))
    r = _chat(REDUCE_PROMPT.format(input="\n\n".join(partials)), cfg)
    _log("info", "总结完成")
    return r
