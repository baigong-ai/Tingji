"""手工冒烟：跑真实音频，验证 ASR 输出。

用法：
    uv run python test/smoke_asr.py /path/to/audio.m4a
"""
import json
import sys
from pathlib import Path

from app.asr import transcribe
from app.config import load_config


def main():
    if len(sys.argv) < 2:
        print("usage: python test/smoke_asr.py <audio_path>")
        sys.exit(1)
    audio_path = sys.argv[1]
    cfg = load_config("config.yaml")
    print(f"loading models and transcribing {audio_path}...")
    result = transcribe(audio_path, cfg.asr)
    print(f"spk_count: {result['spk_count']}")
    print(f"sentences: {len(result['sentences'])}")
    print(f"first 3: {json.dumps(result['sentences'][:3], ensure_ascii=False, indent=2)}")
    out = Path("data") / "smoke_raw.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved to {out}")


if __name__ == "__main__":
    main()
