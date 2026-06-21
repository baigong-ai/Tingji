import json
import shutil
import subprocess


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffmpeg/ffprobe not found. Install via: brew install ffmpeg"
        )


def convert_to_wav(src: str, dst: str) -> None:
    ensure_ffmpeg()
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def get_duration_ms(path: str) -> int:
    ensure_ffmpeg()
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", path,
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    info = json.loads(out)
    duration_s = float(info["streams"][0]["duration"])
    return int(duration_s * 1000)
