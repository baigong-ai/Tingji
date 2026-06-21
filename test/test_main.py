import io
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
