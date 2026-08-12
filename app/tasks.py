import asyncio
import time
import uuid
from typing import Optional

from app import asr, audio, llm, storage

_tasks: dict[str, dict] = {}
_lock = asyncio.Lock()

# B8: 常驻进程里每个 register_task 都往 _tasks 塞且从不清理，跑几周/几百个会议后
# 内存堆几百个 task dict（各带 ≤300 logs）。设上限，注册时清理最旧的终态 task。
_MAX_TASKS = 256
_TERMINAL_STATUSES = {"done", "error", "asr_done"}

CONVERT_END = 5
ASR_FAKE_END = 50
ASR_REAL_END = 55
POLISH_START = 55
POLISH_END = 85
SUMMARY_END = 100

# B10: 进度条 ETA 用的 ASR 实时率（每秒音频耗多少秒识别）。写死 0.25 是 GPU 实测值，
# 在 CPU/Mac 上严重低估（实测 RTF≈4.7），进度条会"假完成"。按 device 给不同 RTF。
_rtf_cache: float | None = None


def _asr_rtf() -> float:
    global _rtf_cache
    if _rtf_cache is not None:
        return _rtf_cache
    try:
        import torch
        if torch.cuda.is_available():
            rtf = 0.025
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            rtf = 0.25
        else:
            rtf = 4.7
    except Exception:
        rtf = 0.25
    _rtf_cache = rtf
    return rtf


def estimate_total_seconds(duration_ms: int) -> float:
    return duration_ms / 1000 * _asr_rtf()


def _prune_tasks() -> None:
    """Keep _tasks bounded. Evicts oldest terminal tasks first; never drops a
    busy (in-flight) task unless there are more than _MAX_TASKS busy at once."""
    if len(_tasks) <= _MAX_TASKS:
        return
    for tid in list(_tasks.keys()):  # dict keeps insertion order
        if len(_tasks) <= _MAX_TASKS:
            break
        if _tasks[tid].get("status") in _TERMINAL_STATUSES:
            del _tasks[tid]
    while len(_tasks) > _MAX_TASKS:  # still over: too many busy, drop oldest
        del _tasks[next(iter(_tasks))]


def register_task(meeting_id: str) -> dict:
    task_id = uuid.uuid4().hex
    state = {
        "task_id": task_id,
        "meeting_id": meeting_id,
        "status": "pending",
        "progress": 0,
        "step": "",
        "error": None,
        "started_at": 0.0,
        "estimated_total_s": 0.0,
        "logs": [],
    }
    _tasks[task_id] = state
    _prune_tasks()
    return state


def latest_task_id(meeting_id: str) -> Optional[str]:
    """Most recently registered task for a meeting (a meeting may accumulate
    several tasks across resume/retry — the newest one is the live one)."""
    for tid, st in reversed(list(_tasks.items())):
        if st["meeting_id"] == meeting_id:
            return tid
    return None


def get_progress(task_id: str) -> Optional[dict]:
    state = _tasks.get(task_id)
    if state is None:
        return None
    return {
        "status": state["status"],
        "progress": state["progress"],
        "step": state["step"],
        "error": state["error"],
    }


def update(task_id: str, **fields) -> None:
    if task_id in _tasks:
        _tasks[task_id].update(fields)


def append_log(meeting_id: str, level: str, msg: str) -> None:
    entry = {"ts": time.time(), "level": level, "msg": msg}
    try:
        storage.append_log_line(meeting_id, entry)
    except Exception:
        pass
    matched = [st for st in _tasks.values() if st["meeting_id"] == meeting_id]
    for st in matched:
        st["logs"].append(entry)
        if len(st["logs"]) > 300:
            st["logs"] = st["logs"][-300:]


def get_logs(meeting_id: str) -> dict:
    tid = latest_task_id(meeting_id)
    if tid is not None:
        st = _tasks[tid]
        return {"status": st["status"], "progress": st["progress"], "step": st["step"], "logs": st["logs"]}
    meta = storage.get_meeting(meeting_id)
    status = meta["meta"]["status"] if meta else "unknown"
    logs = storage.read_log_lines(meeting_id)
    progress = 100 if status == "done" else (ASR_REAL_END if status == "asr_done" else 0)
    return {"status": status, "progress": progress, "step": "", "logs": logs}


def _log_cb(meeting_id: str):
    def cb(level, msg):
        append_log(meeting_id, level, msg)
    return cb


def _resolve_template_hint(tpl_id: str) -> str:
    if not tpl_id:
        return ""
    for t in storage.load_templates():
        if t.get("id") == tpl_id:
            return llm.template_prompt_block(t)
    return ""


def advance_asr_progress(task_id: str, elapsed_s: float) -> None:
    state = _tasks.get(task_id)
    if not state or state.get("estimated_total_s", 0) <= 0:
        return
    ratio = min(elapsed_s / state["estimated_total_s"], 1.0)
    fake_progress = CONVERT_END + int((ASR_FAKE_END - CONVERT_END) * ratio)
    state["progress"] = max(state["progress"], fake_progress)


def _fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    return f"{m}m{s}s"


def _record_timing(meeting_id: str, stage: str, elapsed: float) -> None:
    data = storage.get_meeting(meeting_id)
    if not data:
        return
    timings = (data.get("meta") or {}).get("timings") or {}
    timings[stage] = round(elapsed, 1)
    storage.update_meta(meeting_id, timings=timings)


def _log_stage_summary(meeting_id: str, title: str, *stages) -> None:
    data = storage.get_meeting(meeting_id)
    timings = (data.get("meta") or {}).get("timings") or {} if data else {}
    parts = [f"{label} {_fmt_dur(timings.get(key, 0))}" for key, label in stages]
    total = sum(timings.get(k, 0) for k, _ in stages)
    append_log(meeting_id, "info", f"{title}: {' · '.join(parts)} · 共 {_fmt_dur(total)}")


async def run_pipeline(meeting_id: str, cfg, task_id: Optional[str] = None) -> None:
    async with _lock:
        if task_id is None:
            task_id = latest_task_id(meeting_id)
        if task_id is None:
            task_id = register_task(meeting_id)["task_id"]

        try:
            await _convert_audio(task_id, meeting_id, cfg)
            await _run_asr(task_id, meeting_id, cfg)
            storage.update_meta(meeting_id, status="asr_done")
            update(task_id, status="asr_done", progress=ASR_REAL_END, step="识别完成，待整理")
            _log_stage_summary(meeting_id, "识别阶段完成", ("convert", "转换"), ("asr", "识别"))
        except Exception as e:
            storage.update_meta(meeting_id, status="error", error=str(e))
            update(task_id, status="error", error=str(e), step="失败")


async def _convert_audio(task_id, meeting_id, cfg) -> None:
    update(task_id, status="converting", progress=0, step="音频转换")
    append_log(meeting_id, "info", "音频转换: 转为 16kHz wav ...")
    mdir = storage.meeting_dir(meeting_id)
    meta = storage.get_meeting(meeting_id)["meta"]
    src = mdir / meta["audio_file"]
    dst = mdir / "audio_wav.wav"
    t0 = time.time()
    audio.convert_to_wav(str(src), str(dst))
    convert_s = time.time() - t0
    duration_ms = audio.get_duration_ms(str(dst))
    append_log(meeting_id, "info", f"音频转换完成: 时长 {duration_ms/1000:.0f}s（耗时 {convert_s:.1f}s）")
    storage.update_meta(
        meeting_id,
        audio_wav="audio_wav.wav",
        duration_ms=duration_ms,
    )
    _record_timing(meeting_id, "convert", convert_s)
    update(task_id, progress=CONVERT_END, started_at=time.time(),
           estimated_total_s=estimate_total_seconds(duration_ms))


async def _run_asr(task_id, meeting_id, cfg) -> None:
    update(task_id, status="asr_running", step="语音识别")
    mdir = storage.meeting_dir(meeting_id)
    wav = str(mdir / "audio_wav.wav")
    loop = asyncio.get_running_loop()
    stop_fake = asyncio.Event()

    async def fake_ticker():
        start = time.time()
        while not stop_fake.is_set():
            await asyncio.sleep(2)
            advance_asr_progress(task_id, time.time() - start)

    ticker = asyncio.create_task(fake_ticker())
    t0 = time.time()
    try:
        raw = await loop.run_in_executor(None, asr.transcribe, wav, cfg.asr, _log_cb(meeting_id))
    finally:
        stop_fake.set()
        await ticker
    asr_s = time.time() - t0
    storage.save_raw(meeting_id, raw)
    storage.update_meta(meeting_id, spk_count=raw.get("spk_count", 0))
    _record_timing(meeting_id, "asr", asr_s)
    update(task_id, progress=ASR_REAL_END)


async def _run_polish(task_id, meeting_id, cfg) -> None:
    update(task_id, status="llm_polishing", step="LLM 整理", progress=POLISH_START)
    data = storage.get_meeting(meeting_id)
    if not data["raw"]:
        raise RuntimeError("raw.json missing, cannot polish")
    sentences = data["raw"]["sentences"]
    meta = data.get("meta") or {}
    ctx = meta.get("meeting_context") or ""
    hint = _resolve_template_hint(meta.get("template") or "")
    loop = asyncio.get_running_loop()
    def on_prog(frac):
        update(task_id, progress=int(POLISH_START + frac * (POLISH_END - POLISH_START)))
    t0 = time.time()
    md = await loop.run_in_executor(None, llm.polish, sentences, cfg.llm, _log_cb(meeting_id), on_prog, ctx, hint)
    storage.save_processed(meeting_id, md)
    _record_timing(meeting_id, "polish", time.time() - t0)
    update(task_id, progress=POLISH_END)


async def _run_summarize(task_id, meeting_id, cfg) -> None:
    update(task_id, status="llm_summarizing", step="LLM 总结", progress=POLISH_END)
    data = storage.get_meeting(meeting_id)
    processed = data["processed"] or ""
    meta = data.get("meta") or {}
    ctx = meta.get("meeting_context") or ""
    hint = _resolve_template_hint(meta.get("template") or "")
    loop = asyncio.get_running_loop()
    t0 = time.time()
    result = await loop.run_in_executor(None, llm.summarize, processed, cfg.llm, _log_cb(meeting_id), ctx, hint)
    if isinstance(result, dict):
        storage.save_summary_json(meeting_id, result)
        storage.save_summary(meeting_id, llm.summary_to_md(result))
    else:
        storage.save_summary(meeting_id, result)
        storage.save_summary_json(meeting_id, None)
    _record_timing(meeting_id, "summarize", time.time() - t0)
    update(task_id, progress=SUMMARY_END)


async def retry_llm(meeting_id: str, cfg, task_id: Optional[str] = None) -> str:
    if task_id is None:
        task_id = register_task(meeting_id)["task_id"]
    async with _lock:
        try:
            await _run_polish(task_id, meeting_id, cfg)
            await _run_summarize(task_id, meeting_id, cfg)
            storage.update_meta(meeting_id, status="done", error=None)
            update(task_id, status="done", progress=100, step="完成")
            _log_stage_summary(meeting_id, "整理完成",
                               ("convert", "转换"), ("asr", "识别"), ("polish", "整理"), ("summarize", "总结"))
        except Exception as e:
            storage.update_meta(meeting_id, status="error", error=str(e))
            update(task_id, status="error", error=str(e))
    return task_id


async def finalize_live(meeting_id: str, result: dict, pcm: bytes, sample_rate: int, cfg) -> None:
    """Live stream stopped: persist audio + raw.json + meta(asr_done). Does not take _lock."""
    t0 = time.time()
    fname = storage.save_live_audio(meeting_id, pcm, sample_rate)
    duration_ms = (len(pcm) // 2) * 1000 // sample_rate

    # Second offline pass: run the full ASR pipeline on the saved wav to get
    # accurate text, timestamps, and speaker diarization.
    mdir = storage.meeting_dir(meeting_id)
    wav_path = str(mdir / fname)
    loop = asyncio.get_running_loop()
    try:
        raw = await loop.run_in_executor(None, asr.transcribe, wav_path, cfg.asr, _log_cb(meeting_id))
    except Exception as e:
        append_log(meeting_id, "error", f"实时离线二次识别失败：{e}")
        # Fallback to whatever the streaming engine produced. B12: 流式句的 spk
        # 全是 0，取 set 会得到错误的 spk_count=1；这个 except 是"离线也失败"的
        # 兜底，此时没有可信的说话人信息，直接置 0（详情页可后续手动重映射）。
        sentences = result.get("sentences") or []
        raw = {
            "text": "".join(s.get("text", "") for s in sentences),
            "sentences": sentences,
            "spk_count": 0,
        }

    storage.save_raw(meeting_id, raw)
    storage.update_meta(
        meeting_id,
        status="asr_done",
        audio_file=fname,
        audio_wav=fname,
        duration_ms=duration_ms,
        spk_count=raw.get("spk_count", 0),
    )
    _record_timing(meeting_id, "live", time.time() - t0)
    append_log(meeting_id, "info",
               f"实时记录完成：{len(raw.get('sentences', []))} 句，{raw.get('spk_count', 0)} 位说话人，{duration_ms / 1000:.0f}s")
