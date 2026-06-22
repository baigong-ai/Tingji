import logging
import os
from pathlib import Path
from threading import Lock

from app.config import ASRConfig

log = logging.getLogger(__name__)

_model = None
_lock = Lock()

_LOCAL_DIR_NAMES = {
    "paraformer-zh": "paraformer-zh",
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


def get_model(cfg: ASRConfig):
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        os.environ["FUNASR_HUB"] = cfg.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.cache_dir
        import torch
        if torch.cuda.is_available():
            device = f"cuda ({torch.cuda.get_device_name(0)})"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        log.info("loading FunASR models from %s (hub=%s, device=%s)...", cfg.cache_dir, cfg.hub, device)
        from funasr import AutoModel
        _model = AutoModel(
            model=_resolve_model("paraformer-zh", cfg.cache_dir),
            vad_model=_resolve_model("fsmn-vad", cfg.cache_dir),
            punc_model=_resolve_model("ct-punc", cfg.cache_dir),
            spk_model=_resolve_model("cam++", cfg.cache_dir),
            disable_update=True,
        )
        log.info("FunASR models loaded")
    return _model


def transcribe(wav_path: str, cfg: ASRConfig) -> dict:
    model = get_model(cfg)
    res = model.generate(
        input=wav_path,
        batch_size_s=cfg.batch_size_s,
        batch_size_threshold_s=cfg.batch_size_threshold_s,
        sentence_timestamp=True,
        hotword=cfg.hotword or None,
    )
    return normalize(res)


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
