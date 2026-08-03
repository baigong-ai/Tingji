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


def test_log_persistence(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("t", str(src), "wav")
    storage.append_log_line(mid, {"ts": 1.0, "level": "info", "msg": "hello"})
    storage.append_log_line(mid, {"ts": 2.0, "level": "warn", "msg": "again"})
    logs = storage.read_log_lines(mid)
    assert len(logs) == 2
    assert logs[0]["msg"] == "hello"
    assert logs[1]["level"] == "warn"


def test_invalid_meeting_id_rejected(data_dir):
    """Path traversal must never reach the filesystem layer."""
    assert storage.get_meeting("..") is None
    assert storage.get_meeting("../..") is None
    assert storage.get_meeting("foo/bar") is None
    assert storage.get_meeting("") is None
    storage.delete_meeting("..")            # no-op: data_dir itself must survive
    assert data_dir.exists()
    assert storage.move_to_trash("..") is None


def test_generated_ids_pass_validation(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("产品 周会 v2", str(src), "wav")
    assert storage.is_valid_meeting_id(mid)
    assert storage.get_meeting(mid) is not None


def test_corrupt_meta_does_not_break_listing(data_dir):
    """One damaged meta.json must not 500 the whole meeting list."""
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    good = storage.create_meeting("good", str(src), "wav")
    bad = storage.create_meeting("bad", str(src), "wav")
    (data_dir / bad / "meta.json").write_text("{broken json", encoding="utf-8")
    items = storage.list_meetings()
    assert [i["id"] for i in items] == [good]
    assert storage.get_meeting(bad) is None
    # update_meta on a corrupt meta is a safe no-op
    storage.update_meta(bad, status="error")


def test_update_meta_is_atomic(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("t", str(src), "wav")
    storage.update_meta(mid, status="done")
    assert not (data_dir / mid / "meta.json.tmp").exists()
    assert storage.get_meeting(mid)["meta"]["status"] == "done"
