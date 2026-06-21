import json

import pytest

from app import storage


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return storage.DATA_DIR


def test_create_meeting(data_dir):
    src = data_dir.parent / "src.m4a"
    src.write_bytes(b"audio-bytes")
    mid = storage.create_meeting(title="产品 周会", audio_path=str(src), ext="m4a")
    mdir = data_dir / mid
    assert mdir.exists()
    assert (mdir / "audio.m4a").exists()
    meta = json.loads((mdir / "meta.json").read_text())
    assert meta["title"] == "产品 周会"
    assert meta["status"] == "pending"
    assert meta["audio_file"] == "audio.m4a"


def test_list_meetings_sorted(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    m1 = storage.create_meeting("old", str(src), "wav")
    m2 = storage.create_meeting("new", str(src), "wav")
    items = storage.list_meetings()
    titles = [i["title"] for i in items]
    assert "new" in titles and "old" in titles


def test_save_and_get_meeting(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("t", str(src), "wav")
    storage.save_raw(mid, {"text": "hi", "sentences": [], "spk_count": 0})
    storage.save_processed(mid, "# md")
    storage.save_summary(mid, "## sum")
    storage.update_meta(mid, status="done", spk_count=2)
    data = storage.get_meeting(mid)
    assert data["meta"]["status"] == "done"
    assert data["raw"]["text"] == "hi"
    assert data["processed"] == "# md"
    assert data["summary"] == "## sum"


def test_delete_meeting(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("t", str(src), "wav")
    storage.delete_meeting(mid)
    assert not (data_dir / mid).exists()
    assert storage.get_meeting(mid) is None
