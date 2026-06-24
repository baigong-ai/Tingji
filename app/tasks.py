import asyncio
import time
import uuid
from typing import Optional

from app import asr, audio, llm, storage

_tasks: dict[str, dict] = {}
_lock = asyncio.Lock()

CONVERT_END = 5
ASR_FAKE_END = 50
ASR_REAL_END = 55
POLISH_START = 55
POLISH_END = 85
SUMMARY_END = 100


def estimate_total_seconds(duration_ms: int) -> float:
    return duration_ms / 1000 * 0.25


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
    return state


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
    for st in _tasks.values():
        if st["meeting_id"] == meeting_id:
            st["logs"].append({"ts": time.time(), "level": level, "msg": msg})
            if len(st["logs"]) > 300:
                st["logs"] = st["logs"][-300:]
            return


def get_logs(meeting_id: str) -> dict:
    for st in _tasks.values():
        if st["meeting_id"] == meeting_id:
            return {"status": st["status"], "progress": st["progress"], "step": st["step"], "logs": st["logs"]}
    meta = storage.get_meeting(meeting_id)
    status = meta["meta"]["status"] if meta else "unknown"
    return {"status": status, "progress": 0, "step": "", "logs": []}


def _log_cb(meeting_id: str):
    def cb(level, msg):
        append_log(meeting_id, level, msg)
    return cb


def _resolve_template_hint(tpl_id: str) -> str:
    if not tpl_id:
        return ""
    for t in llm.PRESET_TEMPLATES:
        if t["id"] == tpl_id:
            return t.get("hint", "")
    for t in storage.load_templates():
        if t.get("id") == tpl_id:
            return t.get("hint", "")
    return ""


def advance_asr_progress(task_id: str, elapsed_s: float) -> None:
    state = _tasks.get(task_id)
    if not state or state.get("estimated_total_s", 0) <= 0:
        return
    ratio = min(elapsed_s / state["estimated_total_s"], 1.0)
    fake_progress = CONVERT_END + int((ASR_FAKE_END - CONVERT_END) * ratio)
    state["progress"] = max(state["progress"], fake_progress)


async def run_pipeline(meeting_id: str, cfg) -> None:
    async with _lock:
        task_id = None
        for tid, st in _tasks.items():
            if st["meeting_id"] == meeting_id:
                task_id = tid
                break
        if task_id is None:
            state = register_task(meeting_id)
            task_id = state["task_id"]

        try:
            await _convert_audio(task_id, meeting_id, cfg)
            await _run_asr(task_id, meeting_id, cfg)
            storage.update_meta(meeting_id, status="asr_done")
            update(task_id, status="asr_done", progress=ASR_REAL_END, step="识别完成，待整理")
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
    audio.convert_to_wav(str(src), str(dst))
    duration_ms = audio.get_duration_ms(str(dst))
    append_log(meeting_id, "info", f"音频转换完成: 时长 {duration_ms/1000:.0f}s")
    storage.update_meta(
        meeting_id,
        audio_wav="audio_wav.wav",
        duration_ms=duration_ms,
    )
    update(task_id, progress=CONVERT_END, started_at=time.time(),
           estimated_total_s=estimate_total_seconds(duration_ms))


async def _run_asr(task_id, meeting_id, cfg) -> None:
    update(task_id, status="asr_running", step="语音识别")
    mdir = storage.meeting_dir(meeting_id)
    wav = str(mdir / "audio_wav.wav")
    loop = asyncio.get_event_loop()
    stop_fake = asyncio.Event()

    async def fake_ticker():
        start = time.time()
        while not stop_fake.is_set():
            await asyncio.sleep(2)
            advance_asr_progress(task_id, time.time() - start)

    ticker = asyncio.create_task(fake_ticker())
    try:
        raw = await loop.run_in_executor(None, asr.transcribe, wav, cfg.asr, _log_cb(meeting_id))
    finally:
        stop_fake.set()
        await ticker
    storage.save_raw(meeting_id, raw)
    storage.update_meta(meeting_id, spk_count=raw.get("spk_count", 0))
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
    loop = asyncio.get_event_loop()
    def on_prog(frac):
        update(task_id, progress=int(POLISH_START + frac * (POLISH_END - POLISH_START)))
    md = await loop.run_in_executor(None, llm.polish, sentences, cfg.llm, _log_cb(meeting_id), on_prog, ctx, hint)
    storage.save_processed(meeting_id, md)
    update(task_id, progress=POLISH_END)


async def _run_summarize(task_id, meeting_id, cfg) -> None:
    update(task_id, status="llm_summarizing", step="LLM 总结", progress=POLISH_END)
    data = storage.get_meeting(meeting_id)
    processed = data["processed"] or ""
    meta = data.get("meta") or {}
    ctx = meta.get("meeting_context") or ""
    hint = _resolve_template_hint(meta.get("template") or "")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, llm.summarize, processed, cfg.llm, _log_cb(meeting_id), ctx, hint)
    if isinstance(result, dict):
        storage.save_summary_json(meeting_id, result)
        storage.save_summary(meeting_id, llm.summary_to_md(result))
    else:
        storage.save_summary(meeting_id, result)
        storage.save_summary_json(meeting_id, None)
    update(task_id, progress=SUMMARY_END)


async def retry_llm(meeting_id: str, cfg) -> str:
    state = register_task(meeting_id)
    task_id = state["task_id"]
    async with _lock:
        try:
            await _run_polish(task_id, meeting_id, cfg)
            await _run_summarize(task_id, meeting_id, cfg)
            storage.update_meta(meeting_id, status="done", error=None)
            update(task_id, status="done", progress=100, step="完成")
        except Exception as e:
            storage.update_meta(meeting_id, status="error", error=str(e))
            update(task_id, status="error", error=str(e))
    return task_id
