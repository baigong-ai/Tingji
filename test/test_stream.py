import asyncio
import threading
from unittest import mock

from app import stream
from app.config import ASRConfig


def _engine() -> stream.FunASRStreamEngine:
    return stream.FunASRStreamEngine(
        ASRConfig(cache_dir="models", hub="ms", batch_size_s=300,
                  batch_size_threshold_s=60, hotword="")
    )


def test_feed_decodes_and_punctuates():
    eng = _engine()
    eng._decode = mock.Mock(return_value={"text": "你好世界"})
    eng._punctuate = mock.Mock()
    pcm = b"\x00\x00" * stream.CHUNK_STRIDE
    res = asyncio.run(eng.feed(pcm))
    assert eng._decode.called
    assert eng._punctuate.called
    assert res.duration_ms == len(pcm) // 2 * 1000 // stream.SAMPLE_RATE


def test_punctuate_runs_off_the_event_loop():
    """_punctuate drives the ct-punc model (seconds on first load) — it must
    run in a worker thread, never on the FastAPI event loop."""
    eng = _engine()
    eng._decode = mock.Mock(return_value={"text": "x" * 30})
    threads = []

    def fake_punctuate():
        threads.append(threading.current_thread())

    eng._punctuate = fake_punctuate
    pcm = b"\x00\x00" * stream.CHUNK_STRIDE
    asyncio.run(eng.feed(pcm))
    assert threads, "punctuate was not called"
    assert all(t is not threading.main_thread() for t in threads)


def test_finalize_flushes_and_punctuates_off_loop():
    eng = _engine()
    eng._decode = mock.Mock(return_value={"text": ""})
    eng._punctuate = mock.Mock()
    eng._text_so_far = "剩余文本"
    res = asyncio.run(eng.finalize())
    assert eng._decode.call_count >= 1
    assert eng._punctuate.called
    # trailing text is locked as a final sentence, not lost
    assert any(s["text"] == "剩余文本" for s in res.sentences)
