import logging
import os
from threading import Lock

from app.config import ASRConfig

log = logging.getLogger(__name__)

_model = None
_lock = Lock()


def get_model(cfg: ASRConfig):
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        os.environ["FUNASR_HUB"] = cfg.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.cache_dir
        from funasr import AutoModel
        log.info("loading FunASR models from %s (hub=%s)...", cfg.cache_dir, cfg.hub)
        _model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            vad_revision="v2.0.4",
            punc_model="ct-punc",
            spk_model="cam++",
        )
        log.info("FunASR models loaded")
    return _model


def transcribe(wav_path: str, cfg: ASRConfig) -> dict:
    model = get_model(cfg)
    res = model.generate(
        audio=wav_path,
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
    for s in first.get("sentences", []):
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
