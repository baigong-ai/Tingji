import gc
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Lock

from app.config import ASRConfig

log = logging.getLogger(__name__)

_model = None
_stream_model = None
_punc_model = None
_lock = Lock()
_last_used = 0.0  # epoch seconds of last ASR activity (start or finish)
_stream_last_used = 0.0
_busy = False     # True while a transcription is in flight
_stream_busy = False

_LOCAL_DIR_NAMES = {
    "paraformer-zh": "paraformer-zh",
    "paraformer-zh-streaming": "paraformer-zh-streaming",
    "fsmn-vad": "fsmn-vad",
    "ct-punc": "ct-punc",
    "cam++": "campp",
}


def _resolve_model(alias: str, cache_dir: str) -> str:
    local = Path(cache_dir) / _LOCAL_DIR_NAMES.get(alias, alias)
    if local.exists():
        log.info("using local model: %s", local)
        return str(local)
    log.info("using alias (will auto-download if missing): %s", alias)
    return alias


def is_loaded() -> bool:
    return _model is not None


def is_stream_loaded() -> bool:
    return _stream_model is not None


def is_busy() -> bool:
    return _busy


def is_stream_busy() -> bool:
    return _stream_busy


def last_used_at() -> float:
    return _last_used


def mark_used() -> None:
    global _last_used
    _last_used = time.time()


def mark_stream_used() -> None:
    global _stream_last_used
    _stream_last_used = time.time()


def last_stream_used_at() -> float:
    return _stream_last_used


def _pick_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _rss_mb() -> int:
    """Current process RSS in MB (not peak — peak via getrusage never drops)."""
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True, text=True, timeout=2,
        )
        return int(out.stdout.strip()) // 1024
    except Exception:
        return 0


def _release_os_memory() -> None:
    """Best-effort: nudge the allocator to return freed pages to the OS.

    Without this, freed model objects leave resident pages (especially on
    macOS, where the default allocator doesn't proactively release). On
    Linux/glibc, malloc_trim(0) returns most of them.
    """
    try:
        import ctypes
        if sys.platform == "darwin":
            ctypes.CDLL("libc.dylib").malloc_zone_pressure_relief(None, 0)
        elif hasattr(ctypes, "CDLL"):
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def unload_model() -> bool:
    """Release the loaded FunASR model. Returns True if freed.

    Refuses while a transcription is in flight (_busy). Best-effort GC +
    torch cache clear afterwards so RSS actually drops.
    """
    global _model, _stream_model, _punc_model
    if _model is None and _stream_model is None and _punc_model is None:
        return False
    if _busy or _stream_busy:
        log.info("unload skipped: transcription/stream in flight")
        return False
    with _lock:
        if _model is None and _stream_model is None and _punc_model is None:
            return False
        _model = None
        _stream_model = None
        _punc_model = None
    gc.collect()
    gc.collect()
    _release_os_memory()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    log.info("FunASR models unloaded (idle), RSS≈%dMB", _rss_mb())
    return True


def status() -> dict:
    return {
        "loaded": _model is not None,
        "busy": _busy,
        "last_used_at": _last_used,
        "rss_mb": _rss_mb(),
        "stream_loaded": _stream_model is not None,
        "stream_busy": _stream_busy,
        "stream_last_used_at": _stream_last_used,
    }


def get_model(cfg: ASRConfig):
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        os.environ["FUNASR_HUB"] = cfg.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.cache_dir
        device = _pick_device()
        log.info("loading FunASR models from %s (hub=%s, device=%s)...", cfg.cache_dir, cfg.hub, device)
        from funasr import AutoModel
        _model = AutoModel(
            model=_resolve_model("paraformer-zh", cfg.cache_dir),
            vad_model=_resolve_model("fsmn-vad", cfg.cache_dir),
            punc_model=_resolve_model("ct-punc", cfg.cache_dir),
            spk_model=_resolve_model("cam++", cfg.cache_dir),
            disable_update=True,
            device=device,
        )
        log.info("FunASR models loaded")
    return _model


def get_stream_model(cfg: ASRConfig):
    """Lazy-load streaming paraformer (independent weights from offline paraformer-zh).

    We only load the streaming ASR model here. VAD / punctuation / speaker
    diarization are handled by the offline transcription pass after the live
    session stops, because the streaming VAD+speaker APIs in FunASR have
    incompatible chunk_size signatures for our simple realtime use-case.
    """
    global _stream_model
    if _stream_model is not None:
        return _stream_model
    with _lock:
        if _stream_model is not None:
            return _stream_model
        os.environ["FUNASR_HUB"] = cfg.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.cache_dir
        device = _pick_device()
        log.info("loading FunASR streaming model from %s (hub=%s, device=%s)...", cfg.cache_dir, cfg.hub, device)
        from funasr import AutoModel
        _stream_model = AutoModel(
            model=_resolve_model("paraformer-zh-streaming", cfg.cache_dir),
            disable_update=True,
            device=device,
        )
        log.info("FunASR streaming model loaded")
    return _stream_model


def get_punc_model(cfg: ASRConfig):
    """Lazy-load standalone ct-punc model for realtime caption punctuation."""
    global _punc_model
    if _punc_model is not None:
        return _punc_model
    with _lock:
        if _punc_model is not None:
            return _punc_model
        os.environ["FUNASR_HUB"] = cfg.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.cache_dir
        device = _pick_device()
        log.info("loading FunASR punctuation model from %s (hub=%s, device=%s)...", cfg.cache_dir, cfg.hub, device)
        from funasr import AutoModel
        _punc_model = AutoModel(
            model=_resolve_model("ct-punc", cfg.cache_dir),
            disable_update=True,
            device=device,
        )
        log.info("FunASR punctuation model loaded")
    return _punc_model


def _load_hotword_str() -> str | None:
    """Read user hotwords (one phrase per line in data/hotwords.txt) and
    convert to FunASR's space-separated-char format (e.g. "丁老师" -> "丁 老 师").
    User-edited corrections feed back here to bias later recognition."""
    try:
        from app import storage
        p = Path(storage.get_data_dir()) / "hotwords.txt"
        if not p.exists():
            return None
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return None
        return "\n".join(" ".join(list(line)) for line in lines)
    except Exception as e:
        log.warning("load hotwords failed: %s", e)
        return None


def transcribe(wav_path: str, cfg: ASRConfig, on_log=None) -> dict:
    global _busy
    def _log(level, msg):
        if on_log:
            try:
                on_log(level, msg)
            except Exception:
                pass
    mark_used()
    _log("info", "准备 ASR 模型（首次加载较慢）...")
    model = get_model(cfg)
    try:
        import torch
        if torch.cuda.is_available():
            dev = f"cuda:0 ({torch.cuda.get_device_name(0)})"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            dev = "mps (Apple Silicon GPU)"
        else:
            dev = "cpu"
        _log("info", f"ASR 设备: {dev}")
    except Exception as e:
        _log("warn", f"无法探测设备: {e}")
    hotword = _load_hotword_str() or cfg.hotword or None
    _log("info", "开始语音识别 ...")
    t0 = time.time()
    _busy = True
    try:
        res = model.generate(
            input=wav_path,
            batch_size_s=cfg.batch_size_s,
            batch_size_threshold_s=cfg.batch_size_threshold_s,
            sentence_timestamp=True,
            hotword=hotword,
        )
    finally:
        _busy = False
        mark_used()
    out = normalize(res)
    _log("info", f"识别完成: {len(out['sentences'])} 句, {out['spk_count']} 位说话人 ({time.time()-t0:.1f}s)")
    return out


def normalize(funasr_res: list[dict]) -> dict:
    if not funasr_res:
        return {"text": "", "sentences": [], "spk_count": 0}
    first = funasr_res[0]
    sentences = []
    spk_set = set()
    for s in first.get("sentence_info") or first.get("sentences") or []:
        spk = s.get("spk", 0)
        spk_set.add(spk)
        sentences.append({
            "text": s.get("text", ""),
            "start": s.get("start", 0),
            "end": s.get("end", 0),
            "spk": spk,
        })
    return {
        "text": first.get("text", ""),
        "sentences": sentences,
        "spk_count": len(spk_set) if spk_set else 0,
    }
