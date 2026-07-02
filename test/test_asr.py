from app import asr


import pytest


@pytest.fixture(autouse=True)
def reset_asr_state():
    asr._model = None
    asr._busy = False
    asr._last_used = 0.0
    yield
    asr._model = None
    asr._busy = False
    asr._last_used = 0.0


def test_normalize_funasr_output():
    funasr_res = [
        {
            "text": "你好。世界。",
            "timestamp": [[0, 500], [500, 1000]],
            "sentences": [
                {"text": "你好。", "start": 0, "end": 500, "spk": 0, "timestamp": [[0, 500]]},
                {"text": "世界。", "start": 500, "end": 1000, "spk": 1, "timestamp": [[500, 1000]]},
            ],
        }
    ]
    out = asr.normalize(funasr_res)
    assert out["text"] == "你好。世界。"
    assert len(out["sentences"]) == 2
    assert out["sentences"][0]["spk"] == 0
    assert out["sentences"][1]["end"] == 1000
    assert out["spk_count"] == 2


def test_normalize_missing_sentences_falls_back_to_text():
    funasr_res = [{"text": "x", "timestamp": []}]
    out = asr.normalize(funasr_res)
    assert out["sentences"] == []
    assert out["spk_count"] == 0


def test_unload_model_when_idle():
    asr._model = object()  # sentinel standing in for the real AutoModel
    assert asr.is_loaded()
    assert asr.unload_model() is True
    assert not asr.is_loaded()


def test_unload_refused_when_busy():
    asr._model = object()
    asr._busy = True
    assert asr.unload_model() is False
    assert asr.is_loaded()  # not freed


def test_unload_noop_when_not_loaded():
    assert asr.unload_model() is False


def test_mark_used_updates_timestamp():
    old = asr.last_used_at()
    asr.mark_used()
    assert asr.last_used_at() >= old


def test_status_reports_state():
    asr._model = object()
    asr._busy = True
    s = asr.status()
    assert s["loaded"] is True and s["busy"] is True
    assert s["rss_mb"] >= 0
