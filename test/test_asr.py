from app import asr


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
