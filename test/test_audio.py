import json
from unittest import mock

import pytest

from app import audio


def test_ensure_ffmpeg_present():
    with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        audio.ensure_ffmpeg()


def test_ensure_ffmpeg_missing():
    with mock.patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg"):
            audio.ensure_ffmpeg()


def test_convert_to_wav_invokes_ffmpeg(tmp_path):
    src = tmp_path / "in.m4a"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.wav"
    with mock.patch("app.audio.ensure_ffmpeg"), \
         mock.patch("subprocess.run") as run:
        audio.convert_to_wav(str(src), str(dst))
    assert run.called
    args = run.call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "-ar" in args and "16000" in args
    assert "-ac" in args and "1" in args
    assert str(src) in args and str(dst) in args


def test_get_duration_ms(tmp_path):
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.MagicMock(
            stdout=json.dumps({"streams": [{"duration": "65.5"}]})
        )
        ms = audio.get_duration_ms(str(tmp_path / "x.wav"))
    assert ms == 65500
