import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app import asr
from app.config import ASRConfig, Config

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
STRIDE_SAMPLES = 960          # 60ms @ 16kHz
CHUNK_SIZE = [0, 10, 5]       # 600ms display interval + 300ms lookahead
CHUNK_STRIDE = CHUNK_SIZE[1] * STRIDE_SAMPLES  # 9600 samples = 600ms

_SENTENCE_END_RE = re.compile(r"([。！？.?!,，;；])")


@dataclass
class StreamResult:
    sentences: list[dict] = field(default_factory=list)
    partial: str = ""
    partial_start_ms: int = 0
    duration_ms: int = 0


class StreamEngine:
    """Abstract realtime streaming engine."""

    async def start(self, hotwords: Optional[list[str]], language: Optional[str]) -> None:
        raise NotImplementedError

    async def feed(self, pcm: bytes) -> StreamResult:
        raise NotImplementedError

    async def finalize(self) -> StreamResult:
        raise NotImplementedError

    def snapshot(self) -> StreamResult:
        raise NotImplementedError

    def pcm_bytes(self) -> bytes:
        """Return all PCM received so far (int16 mono)."""
        raise NotImplementedError

    def status(self) -> dict:
        return {"type": type(self).__name__}

    async def close(self) -> None:
        pass


class FunASRStreamEngine(StreamEngine):
    """In-process FunASR SDK streaming (paraformer-zh-streaming only).

    Speaker diarization and accurate timestamps are produced in a second
    offline pass after the live session stops, because the streaming VAD/speaker
    APIs in FunASR have incompatible chunk_size signatures for a simple realtime
    loop. This engine gives the user fast realtime partial text; final quality
    comes from the offline ASR pass on the saved wav.
    """

    def __init__(self, cfg: ASRConfig):
        self.cfg = cfg
        self._model = None
        self._cache: dict = {}
        self._audio = bytearray()          # all PCM received
        self._chunk_buf = bytearray()      # PCM waiting to reach CHUNK_STRIDE
        self._sentences: list[dict] = []
        self._partial = ""
        self._partial_start_ms = 0
        self._text_so_far = ""
        self._sentence_start_ms = 0
        self._closed = False
        self._hotword_str: Optional[str] = None

    async def start(self, hotwords: Optional[list[str]], language: Optional[str]) -> None:
        asr._stream_busy = True
        asr.mark_stream_used()
        if hotwords:
            # FunASR streaming expects space-separated characters.
            self._hotword_str = "\n".join(" ".join(list(w)) for w in hotwords)

    def _load_model(self):
        if self._model is None:
            self._model = asr.get_stream_model(self.cfg)
        return self._model

    def _pcm_to_float(self, pcm: bytes) -> np.ndarray:
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        return arr / 32768.0

    def _decode(self, chunk: bytes, is_final: bool = False) -> dict:
        model = self._load_model()
        audio = self._pcm_to_float(chunk)
        if len(audio) == 0:
            return {}
        kwargs = {
            "input": audio,
            "cache": self._cache,
            "is_final": is_final,
            "chunk_size": CHUNK_SIZE,
            "encoder_chunk_look_back": 4,
            "decoder_chunk_look_back": 1,
        }
        if self._hotword_str:
            kwargs["hotword"] = self._hotword_str
        try:
            res = model.generate(**kwargs)
        except Exception as e:
            log.warning("streaming decode error: %s", e)
            return {}
        if not res:
            return {}
        first = res[0] if isinstance(res, list) else res
        return first if isinstance(first, dict) else {}

    def _split_to_sentences(self, text: str) -> list[str]:
        """Split streaming text into sentence-like chunks by punctuation."""
        if not text:
            return []
        parts = _SENTENCE_END_RE.split(text)
        out = []
        buf = ""
        for part in parts:
            if not part:
                continue
            if _SENTENCE_END_RE.match(part):
                buf += part
                out.append(buf.strip())
                buf = ""
            else:
                buf += part
        if buf.strip():
            out.append(buf.strip())
        return out

    def _append_sentences(self, text: str) -> None:
        """Lock completed sentences from the streaming text."""
        if not text:
            return
        # Keep only newly completed sentences (text that already ended with punctuation
        # and is no longer at the tail of the stream).
        split = self._split_to_sentences(text)
        if not split:
            return
        # The last chunk may still grow; lock all but the last one if it has no ending punct.
        locked = split[:-1]
        if _SENTENCE_END_RE.search(split[-1]):
            locked = split
        base_ms = self._sentence_start_ms
        for s in locked:
            if not any(s == ex["text"] for ex in self._sentences):
                dur = max(len(s) * 220, 1000)  # rough ~220ms/char, at least 1s
                self._sentences.append({
                    "text": s,
                    "start": base_ms,
                    "end": base_ms + dur,
                    "spk": 0,
                })
                base_ms += dur
        self._sentence_start_ms = base_ms

    def _update_partial(self, text: str) -> None:
        self._partial = text
        self._partial_start_ms = self.duration_ms()

    def duration_ms(self) -> int:
        return len(self._audio) // 2 * 1000 // SAMPLE_RATE

    async def feed(self, pcm: bytes) -> StreamResult:
        asr.mark_stream_used()
        self._audio.extend(pcm)
        self._chunk_buf.extend(pcm)
        while len(self._chunk_buf) >= CHUNK_STRIDE * 2:
            block = bytes(self._chunk_buf[: CHUNK_STRIDE * 2])
            del self._chunk_buf[: CHUNK_STRIDE * 2]
            result = await asyncio.to_thread(self._decode, block, is_final=False)
            text = result.get("text", "") or ""
            self._append_sentences(text)
            self._update_partial(text)
        return self.snapshot()

    async def finalize(self) -> StreamResult:
        if self._chunk_buf:
            block = bytes(self._chunk_buf)
            self._chunk_buf.clear()
            result = await asyncio.to_thread(self._decode, block, is_final=True)
            text = result.get("text", "") or ""
            self._append_sentences(text)
            self._update_partial(text)
        # Flush cache with empty audio to get any trailing text.
        await asyncio.to_thread(self._decode, b"", is_final=True)
        return self.snapshot()

    def snapshot(self) -> StreamResult:
        return StreamResult(
            sentences=list(self._sentences),
            partial=self._partial,
            partial_start_ms=self._partial_start_ms,
            duration_ms=self.duration_ms(),
        )

    def pcm_bytes(self) -> bytes:
        return bytes(self._audio)

    def status(self) -> dict:
        return {"type": "funasr", "duration_ms": self.duration_ms()}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        asr._stream_busy = False
        asr.mark_stream_used()


class SidecarStreamEngine(StreamEngine):
    """Proxy to Fun-ASR-Nano vLLM sidecar (Plan A, WSL+GPU only).

    Protocol (serve_realtime_ws.py):
        START -> {"event":"started"}
        HOTWORDS:word1,word2 -> {"event":"hotwords_set"}
        LANGUAGE:zh -> {"event":"language_set"}
        <PCM int16 16kHz mono chunks> -> {"sentences":[...],"partial":"..."}
        STOP -> {"sentences":[...],"is_final":true}
    """

    def __init__(self, cfg: ASRConfig):
        self.url = cfg.sidecar_url
        self._audio = bytearray()
        self._sentences: list[dict] = []
        self._partial = ""
        self._partial_start_ms = 0
        self._ws = None
        self._reader_task = None
        self._closed = False

    async def start(self, hotwords: Optional[list[str]], language: Optional[str]) -> None:
        asr._stream_busy = True
        asr.mark_stream_used()
        import websockets
        try:
            self._ws = await websockets.connect(self.url, max_size=10 * 1024 * 1024)
        except Exception as e:
            asr._stream_busy = False
            asr.mark_stream_used()
            raise RuntimeError(f"无法连接到增强模式引擎（{self.url}）：{e}") from e
        await self._ws.send("START")
        # drain initial ack
        ack = await asyncio.wait_for(self._ws.recv(), timeout=5)
        log.debug("sidecar ack: %s", ack)
        if hotwords:
            await self._ws.send("HOTWORDS:" + ",".join(hotwords))
        if language:
            await self._ws.send("LANGUAGE:" + language)
        self._reader_task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        """Background reader: merge sidecar sentences/partial into local state."""
        if self._ws is None:
            return
        try:
            async for msg in self._ws:
                if isinstance(msg, bytes):
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                new_sentences = data.get("sentences") or []
                # Merge by (text, start, end) to avoid duplicates on retransmissions.
                for s in new_sentences:
                    item = {
                        "text": s.get("text", ""),
                        "start": int(s.get("start", 0)),
                        "end": int(s.get("end", 0)),
                        "spk": int(s.get("spk", 0)),
                    }
                    if not any(
                        item["text"] == ex["text"]
                        and item["start"] == ex["start"]
                        and item["end"] == ex["end"]
                        for ex in self._sentences
                    ):
                        self._sentences.append(item)
                if "partial" in data:
                    self._partial = data.get("partial", "")
                    self._partial_start_ms = data.get("partial_start_ms", self.duration_ms())
        except Exception as e:
            log.warning("sidecar pump ended: %s", e)

    async def feed(self, pcm: bytes) -> StreamResult:
        asr.mark_stream_used()
        self._audio.extend(pcm)
        if self._ws is not None:
            await self._ws.send(pcm)
        return self.snapshot()

    async def finalize(self) -> StreamResult:
        if self._ws is not None:
            await self._ws.send("STOP")
            # Wait a short moment for final messages to arrive.
            try:
                await asyncio.wait_for(self._ws.recv(), timeout=5)
            except Exception:
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        return self.snapshot()

    def snapshot(self) -> StreamResult:
        return StreamResult(
            sentences=list(self._sentences),
            partial=self._partial,
            partial_start_ms=self._partial_start_ms,
            duration_ms=self.duration_ms(),
        )

    def duration_ms(self) -> int:
        return len(self._audio) // 2 * 1000 // SAMPLE_RATE

    def pcm_bytes(self) -> bytes:
        return bytes(self._audio)

    def status(self) -> dict:
        return {"type": "sidecar", "url": self.url, "duration_ms": self.duration_ms()}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        asr._stream_busy = False
        asr.mark_stream_used()


def load_hotwords() -> Optional[list[str]]:
    """Return user hotwords as plain phrases (not space-split)."""
    try:
        from app import storage
        p = storage.get_data_dir() / "hotwords.txt"
        if not p.exists():
            return None
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        return lines if lines else None
    except Exception as e:
        log.warning("load hotwords failed: %s", e)
        return None


def make_engine(cfg: Config) -> StreamEngine:
    engine = (getattr(cfg.asr, "stream_engine", None) or "funasr").lower()
    if engine == "sidecar":
        return SidecarStreamEngine(cfg.asr)
    return FunASRStreamEngine(cfg.asr)


def result_to_dict(result: StreamResult) -> dict:
    return {
        "sentences": result.sentences,
        "partial": result.partial,
        "partial_start_ms": result.partial_start_ms,
        "duration_ms": result.duration_ms,
    }
