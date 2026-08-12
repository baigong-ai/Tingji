import json
import logging
import re
import time
import urllib.error
import urllib.request

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

SUMMARIZE_PROMPT = """下面是一份整理后的会议记录。请输出**严格的 JSON**（不要 markdown 代码块、不要任何额外文字），结构必须是：

{{"summary": "会议核心内容概述，1-3 句", "decisions": ["已确定的事项，每条一句"], "action_items": ["待办事项，尽量括注负责人"], "open_questions": ["未解决或待讨论的问题"]}}

四个字段都要有，没内容的给空数组 []。只输出 JSON 本身。

会议记录：
{input}
"""

REDUCE_PROMPT = """下面是同一会议多个分段各自输出的会议纪要 JSON。请合并为一份统一的 JSON（同样结构：summary/decisions/action_items/open_questions），去重，summary 给出综合概述。只输出 JSON 本身。

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


class EmptyLLMResponse(RuntimeError):
    """LLM 调用没报错但返回了空内容（典型：思考型模型 reasoning 失控，
    content 为空）。必须当失败处理，否则空结果会被静默拼接进整理稿。"""


def _chat_api(prompt: str, cfg: LLMConfig, json_mode: bool) -> str:
    # /no_think 后缀只对 Ollama 的思考型模型有意义（见 _chat_ollama 用原生 think:false），
    # 对 GLM/DeepSeek 等 API 是无害但无意义的 prompt 污染，这里不追加。
    client = _client(cfg)
    kwargs = {
        "model": _model_name(cfg),
        "messages": [{"role": "user", "content": prompt.rstrip()}],
        "temperature": cfg.temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return _clean_response(resp.choices[0].message.content or "")


def _chat_ollama(prompt: str, cfg: LLMConfig, json_mode: bool) -> str:
    """Ollama 走原生 /api/chat 而不是 OpenAI 兼容接口：只有原生接口支持
    think:false。思考型模型（如 qwen3.5）不关思考时 reasoning 会失控，
    content 直接返回空；OpenAI 兼容接口不认 think/chat_template_kwargs，
    /no_think 后缀在该模型上反而加剧失控（均已实测验证）。"""
    base = cfg.ollama.base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    payload = {
        "model": cfg.ollama.model,
        "messages": [{"role": "user", "content": prompt.rstrip()}],
        "stream": False,
        "think": False,
        # num_ctx: ollama 默认 4096，长会议整理/总结会超限，放宽到 16k
        "options": {"num_ctx": 16384, "temperature": cfg.temperature},
    }
    if json_mode:
        payload["format"] = "json"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        base + "/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            d = json.load(resp)
    except urllib.error.HTTPError as e:
        # 老版本 Ollama / 不支持 thinking 的模型可能拒绝 think 字段，降级重试
        detail = e.read().decode(errors="replace")
        if e.code == 400 and "think" in detail.lower():
            payload.pop("think", None)
            req = urllib.request.Request(
                base + "/api/chat", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=900) as resp:
                d = json.load(resp)
        else:
            raise RuntimeError(f"ollama /api/chat HTTP {e.code}: {detail}") from e
    return _clean_response((d.get("message") or {}).get("content") or "")


def _chat(prompt: str, cfg: LLMConfig, json_mode: bool = False) -> str:
    if cfg.mode == "ollama":
        text = _chat_ollama(prompt, cfg, json_mode)
    else:
        text = _chat_api(prompt, cfg, json_mode)
    if not text:
        raise EmptyLLMResponse(f"LLM 返回空内容（模型 {_model_name(cfg)}）")
    return text


def _chat_retry(prompt: str, cfg: LLMConfig, json_mode: bool = False) -> str:
    attempts = cfg.max_retries + 1
    for i in range(attempts):
        try:
            return _chat(prompt, cfg, json_mode=json_mode)
        except Exception as e:
            log.warning("llm chat failed (attempt %d/%d): %s", i + 1, attempts, e)
            if i == attempts - 1:
                raise


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


def _context_block(meeting_context: str) -> str:
    c = (meeting_context or "").strip()
    if not c:
        return ""
    return "会议背景（用户提供，整理/总结时参考；术语、人名、产品名以此为准）：\n" + c + "\n\n"


DEFAULT_TEMPLATES = [
    {"id": "general", "name": "普通会议", "background": "", "terms": "", "direction": "全面总结会议讨论的内容", "content": "核心议题、决议、待办、待讨论问题", "framework": "概述 + 决议 + 待办 + 待讨论"},
    {"id": "weekly", "name": "周会", "background": "", "terms": "", "direction": "聚焦本周进展、阻塞与下周计划", "content": "各人进展、阻塞点、下周待办", "framework": "进展 + 阻塞 + 待办（带负责人）"},
    {"id": "interview", "name": "访谈采访", "background": "", "terms": "", "direction": "围绕访谈主题提炼观点与故事", "content": "访谈主题、关键观点、金句、待跟进问题", "framework": "主题 + 观点 + follow-up"},
    {"id": "project", "name": "项目管理", "background": "", "terms": "", "direction": "聚焦任务、责任人与里程碑", "content": "任务进展、负责人、里程碑、风险", "framework": "任务 + 负责人 + 里程碑 + 风险"},
]


def template_prompt_block(tpl: dict) -> str:
    if not tpl:
        return ""
    parts = []
    if str(tpl.get("background", "")).strip():
        parts.append("会议背景：" + tpl["background"].strip())
    if str(tpl.get("terms", "")).strip():
        parts.append("常用术语/人名/产品名（以此为准，纠正识别错误）：" + tpl["terms"].strip())
    if str(tpl.get("direction", "")).strip():
        parts.append("总结方向：" + tpl["direction"].strip())
    if str(tpl.get("content", "")).strip():
        parts.append("总结内容侧重：" + tpl["content"].strip())
    if str(tpl.get("framework", "")).strip():
        parts.append("总结框架：" + tpl["framework"].strip())
    return ("模板要求：\n" + "\n".join(parts) + "\n\n") if parts else ""


def polish(sentences: list[dict], cfg: LLMConfig, on_log=None, on_progress=None, meeting_context: str = "", template_hint: str = "") -> str:
    def _log(level, msg):
        if on_log:
            try:
                on_log(level, msg)
            except Exception:
                pass
    chunks = chunk_sentences(sentences, cfg.polish_chunk_minutes)
    ctx = _context_block(meeting_context) + (template_hint or "")
    _log("info", f"整理: 共 {len(chunks)} 段, 模型 {_model_name(cfg)}")
    outputs = []
    for i, chunk in enumerate(chunks):
        t0 = time.time()
        _log("info", f"整理第 {i+1}/{len(chunks)} 段 ...")
        prompt = ctx + POLISH_PROMPT.format(input=format_chunk(chunk))
        try:
            outputs.append(_chat_retry(prompt, cfg))
        except Exception as e:
            log.warning("polish chunk %d failed: %s", i + 1, e)
            _log("warn", f"第 {i+1} 段整理失败（{e}）, 保留原文")
            outputs.append(format_chunk(chunk, mark_failed=True))
            continue
        _log("info", f"整理第 {i+1}/{len(chunks)} 段完成 ({time.time()-t0:.1f}s)")
        if on_progress:
            try:
                on_progress((i + 1) / len(chunks))
            except Exception:
                pass
    _log("info", f"整理完成, 共 {len(chunks)} 段")
    return "\n\n---\n\n".join(outputs)


def _split_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def _parse_summary_json(text: str) -> dict | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*", "", s).strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    try:
        d = json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except Exception:
            return None

    def _items(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    return {
        "summary": str(d.get("summary", "")).strip(),
        "decisions": _items(d.get("decisions")),
        "action_items": _items(d.get("action_items")),
        "open_questions": _items(d.get("open_questions")),
    }


def summary_to_md(d: dict) -> str:
    parts = []
    if d.get("summary"):
        parts.append(f"## 概述\n\n{d['summary']}")
    if d.get("decisions"):
        parts.append("## 决议\n\n" + "\n".join(f"- {x}" for x in d["decisions"]))
    if d.get("action_items"):
        parts.append("## 待办\n\n" + "\n".join(f"- [ ] {x}" for x in d["action_items"]))
    if d.get("open_questions"):
        parts.append("## 待讨论\n\n" + "\n".join(f"- {x}" for x in d["open_questions"]))
    return "\n\n".join(parts)


def summarize(processed_md: str, cfg: LLMConfig, on_log=None, meeting_context: str = "", template_hint: str = "") -> dict | str:
    def _log(level, msg):
        if on_log:
            try:
                on_log(level, msg)
            except Exception:
                pass
    ctx = _context_block(meeting_context) + (template_hint or "")
    if len(processed_md) < 8000:
        t0 = time.time()
        _log("info", f"生成总结, 模型 {_model_name(cfg)}")
        raw = _chat_retry(ctx + SUMMARIZE_PROMPT.format(input=processed_md), cfg, json_mode=True)
        _log("info", f"总结完成 ({time.time()-t0:.1f}s)")
        return _parse_summary_json(raw) or raw
    chunks = _split_text(processed_md, 6000)
    _log("info", f"总结: 长文 map-reduce, 切 {len(chunks)} 块")
    partials = []
    for i, c in enumerate(chunks):
        t0 = time.time()
        _log("info", f"总结第 {i+1}/{len(chunks)} 块 ...")
        partials.append(_chat_retry(ctx + SUMMARIZE_PROMPT.format(input=c), cfg, json_mode=True))
        _log("info", f"总结第 {i+1}/{len(chunks)} 块完成 ({time.time()-t0:.1f}s)")
    _log("info", "合并总结 ...")
    raw = _chat_retry(ctx + REDUCE_PROMPT.format(input="\n\n".join(partials)), cfg, json_mode=True)
    _log("info", "总结完成")
    return _parse_summary_json(raw) or raw
