import io
import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import main, storage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)

    async def fake_run(meeting_id, cfg):
        storage.update_meta(meeting_id, status="done")
    monkeypatch.setattr(main.tasks, "run_pipeline", fake_run)

    with TestClient(main.app) as c:
        yield c


def test_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_upload_and_list(client):
    audio_bytes = b"fake-audio"
    files = {"audio": ("m.m4a", io.BytesIO(audio_bytes), "audio/m4a")}
    data = {"title": "Demo Meeting"}
    r = client.post("/api/upload", files=files, data=data)
    assert r.status_code == 200
    body = r.json()
    assert "meeting_id" in body and "task_id" in body
    meetings = client.get("/api/meetings").json()
    assert any(m["id"] == body["meeting_id"] for m in meetings)


def test_upload_rejects_non_audio(client):
    files = {"audio": ("t.txt", io.BytesIO(b"x"), "text/plain")}
    data = {"title": "x"}
    r = client.post("/api/upload", files=files, data=data)
    assert r.status_code == 415


def test_get_meeting(client):
    files = {"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}
    r = client.post("/api/upload", files=files, data={"title": "T"})
    mid = r.json()["meeting_id"]
    detail = client.get(f"/api/meetings/{mid}").json()
    assert detail["meta"]["id"] == mid


def test_delete_meeting(client):
    files = {"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}
    mid = client.post("/api/upload", files=files, data={"title": "T"}).json()["meeting_id"]
    r = client.delete(f"/api/meetings/{mid}")
    assert r.status_code == 200
    assert client.get(f"/api/meetings/{mid}").status_code == 404


def test_rename_speakers_persists(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.put(f"/api/meetings/{mid}/speakers", json={"names": {"0": "Alice", "1": "Bob"}})
    assert r.status_code == 200
    meta = client.get(f"/api/meetings/{mid}").json()["meta"]
    assert meta["speaker_names"] == {"0": "Alice", "1": "Bob"}


def test_export_txt_uses_speaker_names(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    storage.save_raw(mid, {"sentences": [
        {"start": 0, "end": 1000, "spk": 0, "text": "hi"},
        {"start": 1100, "end": 2000, "spk": 1, "text": "yo"},
    ]})
    client.put(f"/api/meetings/{mid}/speakers", json={"names": {"0": "Alice", "1": "Bob"}})
    txt = client.get(f"/api/meetings/{mid}/export?format=txt").text
    assert "Alice" in txt and "Bob" in txt
    assert "说话人0" not in txt and "说话人1" not in txt


def test_export_srt_uses_speaker_names(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    storage.save_raw(mid, {"sentences": [{"start": 0, "end": 1000, "spk": 0, "text": "hi"}]})
    client.put(f"/api/meetings/{mid}/speakers", json={"names": {"0": "Alice"}})
    srt = client.get(f"/api/meetings/{mid}/export?format=srt").text
    assert "[Alice]" in srt


def test_browse_lists_only_subdirs(client, tmp_path):
    (tmp_path / "subA").mkdir()
    (tmp_path / "subB").mkdir()
    (tmp_path / "file.txt").write_text("x")
    body = client.get("/api/browse", params={"path": str(tmp_path)}).json()
    names = [d["name"] for d in body["dirs"]]
    assert "subA" in names and "subB" in names
    assert "file.txt" not in names
    assert body["writable"] is True
    assert body["parent"] is not None


def test_migrate_moves_meetings(client, tmp_path):
    src = tmp_path / "old_data"
    m = src / "m1"
    m.mkdir(parents=True)
    (m / "meta.json").write_text(json.dumps({"id": "m1", "title": "t"}))
    (m / "audio.wav").write_bytes(b"audio")
    (m / "sub").mkdir()
    (m / "sub" / "nested.json").write_text("{}")
    body = client.post("/api/settings/migrate", json={"from_dir": str(src)}).json()
    assert body["count"] == 1
    assert "m1" in body["moved"]
    dst_meeting = storage.get_data_dir() / "m1"
    assert (dst_meeting / "meta.json").exists()
    assert (dst_meeting / "audio.wav").exists()
    assert (dst_meeting / "sub" / "nested.json").exists()  # nested dirs copied
    assert not m.exists()  # source removed


def test_edit_sentence(client):
    files = {"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}
    mid = client.post("/api/upload", files=files, data={"title": "T"}).json()["meeting_id"]
    storage.save_raw(mid, {"sentences": [{"start": 0, "end": 100, "spk": 0, "text": "旧文本"}]})
    r = client.put(f"/api/meetings/{mid}/sentence", json={"index": 0, "text": "新文本"})
    assert r.status_code == 200
    after = client.get(f"/api/meetings/{mid}").json()["raw"]["sentences"][0]["text"]
    assert after == "新文本"


def test_edit_sentence_rejects_bad_index(client):
    files = {"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}
    mid = client.post("/api/upload", files=files, data={"title": "T"}).json()["meeting_id"]
    storage.save_raw(mid, {"sentences": [{"start": 0, "end": 100, "spk": 0, "text": "x"}]})
    assert client.put(f"/api/meetings/{mid}/sentence", json={"index": 5, "text": "y"}).status_code == 400
    assert client.put(f"/api/meetings/{mid}/sentence", json={"index": 0, "text": ""}).status_code == 400


def test_hotwords_roundtrip(client):
    r = client.post("/api/settings/hotwords", json={"hotwords": ["丁老师", "云南"]})
    assert r.status_code == 200 and r.json()["count"] == 2
    got = client.get("/api/settings/hotwords").json()["hotwords"]
    assert got == ["丁老师", "云南"]


def test_hotwords_dedup(client):
    r = client.post("/api/settings/hotwords", json={"hotwords": ["a", "b", "a", "b", "c"]})
    assert r.json()["count"] == 3 and r.json()["duplicates"] == 2
    got = client.get("/api/settings/hotwords").json()["hotwords"]
    assert got == ["a", "b", "c"]
