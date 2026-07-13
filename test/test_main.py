import io
import json
import time
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


def test_delete_meeting_keep_moves_to_trash(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.delete(f"/api/meetings/{mid}?keep=1")
    assert r.status_code == 200
    body = r.json()
    assert body["trashed"] is True
    # gone from history list
    assert not any(m["id"] == mid for m in client.get("/api/meetings").json())
    # files preserved under visible 回收站 dir
    trash = storage.trash_dir()
    assert trash.name == "回收站"
    moved = list(trash.iterdir())
    assert len(moved) == 1
    assert (moved[0] / "meta.json").exists()
    assert body["trash_path"].endswith("回收站/" + moved[0].name)


def test_delete_meeting_full_removes_files(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.delete(f"/api/meetings/{mid}")
    assert r.json()["trashed"] is False
    assert not storage.meeting_dir(mid).exists()


def test_rename_meeting(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "旧名"}).json()["meeting_id"]
    r = client.put(f"/api/meetings/{mid}/title", json={"title": "新名字"})
    assert r.status_code == 200 and r.json()["title"] == "新名字"
    assert client.get(f"/api/meetings/{mid}").json()["meta"]["title"] == "新名字"


def test_rename_meeting_rejects_empty(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    assert client.put(f"/api/meetings/{mid}/title", json={"title": "  "}).status_code == 400


def test_set_tags(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.put(f"/api/meetings/{mid}/tags", json={"tags": ["周会", "产品", "周会"]})
    assert r.status_code == 200
    assert r.json()["tags"] == ["周会", "产品"]  # de-duped, order kept
    meta = client.get(f"/api/meetings/{mid}").json()["meta"]
    assert meta["tags"] == ["周会", "产品"]


def test_set_tags_rejects_bad_shape(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    assert client.put(f"/api/meetings/{mid}/tags", json={"tags": "not-a-list"}).status_code == 400


def test_trash_not_listed_as_meeting(client):
    # 回收站 dir itself must not appear in the meeting list
    storage.trash_dir().mkdir(parents=True, exist_ok=True)
    meetings = client.get("/api/meetings").json()
    assert all("回收站" not in m["id"] for m in meetings)


def test_rename_speakers_persists(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.put(f"/api/meetings/{mid}/speakers", json={"names": {"0": "Alice", "1": "Bob"}})
    assert r.status_code == 200
    meta = client.get(f"/api/meetings/{mid}").json()["meta"]
    assert meta["speaker_names"] == {"0": "Alice", "1": "Bob"}


def test_set_meeting_context_persists(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.put(f"/api/meetings/{mid}/context", json={"meeting_context": "X 项目周会；术语：K8s"})
    assert r.status_code == 200
    meta = client.get(f"/api/meetings/{mid}").json()["meta"]
    assert meta["meeting_context"] == "X 项目周会；术语：K8s"


def test_templates_seed_and_roundtrip(client):
    d = client.get("/api/settings/templates").json()
    tpls = d["templates"]
    assert any(t["id"] == "general" for t in tpls)
    assert any(t["name"] == "周会" for t in tpls)
    client.put("/api/settings/templates", json={"templates": tpls + [{"name": "播客剪辑", "direction": "话题脉络"}]})
    d2 = client.get("/api/settings/templates").json()
    assert any(t["name"] == "播客剪辑" for t in d2["templates"])
    assert d2["templates"][-1]["id"].startswith("c-")
    assert d2["templates"][-1]["direction"] == "话题脉络"


def test_set_meeting_template(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    r = client.put(f"/api/meetings/{mid}/context", json={"template": "company"})
    assert r.status_code == 200
    assert client.get(f"/api/meetings/{mid}").json()["meta"]["template"] == "company"


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


def test_export_md_uses_speaker_names(client):
    mid = client.post("/api/upload", files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}, data={"title": "T"}).json()["meeting_id"]
    storage.save_processed(mid, "## 说话人 0\n\n你好\n\n## 说话人1\n\n嗯\n")
    client.put(f"/api/meetings/{mid}/speakers", json={"names": {"0": "Alice", "1": "Bob"}})
    md = client.get(f"/api/meetings/{mid}/export?format=md").text
    assert "Alice" in md and "Bob" in md
    assert "说话人0" not in md and "说话人1" not in md


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


# --- ASR status / unload ---
def test_asr_status(client):
    d = client.get("/api/asr/status").json()
    assert "loaded" in d and "rss_mb" in d and "idle_unload_minutes" in d


def test_asr_unload_when_idle(client, monkeypatch):
    main.tasks._tasks.clear()
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", False)
    r = client.post("/api/asr/unload")
    assert r.status_code == 200
    assert r.json()["unloaded"] is True


def test_asr_unload_refused_when_busy(client, monkeypatch):
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", True)
    assert client.post("/api/asr/unload").status_code == 409


def test_asr_unload_refused_when_task_pending(client, monkeypatch):
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", False)
    main.tasks._tasks["t1"] = {"status": "asr_running"}
    try:
        assert client.post("/api/asr/unload").status_code == 409
    finally:
        main.tasks._tasks.clear()


# --- port check / server settings ---
def test_port_check_free(client):
    import socket as _s
    sk = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    sk.bind(("0.0.0.0", 0))
    free_port = sk.getsockname()[1]
    sk.close()
    d = client.post("/api/settings/server/check", json={"port": free_port, "host": "0.0.0.0"}).json()
    assert d["ok"] is True and d["self"] is False


def test_port_check_conflict(client):
    import socket as _s
    sk = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    sk.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 0)
    sk.bind(("0.0.0.0", 0))
    sk.listen(1)
    held_port = sk.getsockname()[1]
    try:
        d = client.post("/api/settings/server/check", json={"port": held_port, "host": "0.0.0.0"}).json()
        assert d["ok"] is False
    finally:
        sk.close()


def test_port_check_self(client):
    d = client.post("/api/settings/server/check", json={"port": main._RUNNING_PORT, "host": "0.0.0.0"}).json()
    assert d["ok"] is True and d["self"] is True


def test_port_check_rejects_invalid(client):
    assert client.post("/api/settings/server/check", json={"port": 0}).status_code == 400
    assert client.post("/api/settings/server/check", json={"port": 70000}).status_code == 400


def test_server_settings_roundtrip(client, monkeypatch):
    monkeypatch.setattr(main, "_persist_server_config", lambda *a, **kw: None)
    prev = (main.config.server.host, main.config.server.port, main.config.asr.idle_unload_minutes)
    try:
        r = client.post("/api/settings/server", json={
            "port": 9999, "host": "127.0.0.1", "idle_unload_minutes": 5})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] and d["restart_required"] is True  # 9999 != running port
        assert main.config.server.port == 9999
        assert main.config.asr.idle_unload_minutes == 5
        got = client.get("/api/settings/server").json()
        assert got["port"] == 9999 and got["running_port"] == main._RUNNING_PORT
    finally:
        main.config.server.host, main.config.server.port = prev[0], prev[1]
        main.config.asr.idle_unload_minutes = prev[2]


# --- idle watcher decision logic ---
def test_idle_check_unloads_when_idle(client, monkeypatch):
    main.tasks._tasks.clear()
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", False)
    monkeypatch.setattr(main.asr, "_last_used", time.time() - 1000)
    assert main._idle_check(60) is True
    assert not main.asr.is_loaded()


def test_idle_check_skips_when_below_threshold(client, monkeypatch):
    main.tasks._tasks.clear()
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", False)
    monkeypatch.setattr(main.asr, "_last_used", time.time())
    assert main._idle_check(3600) is False
    assert main.asr.is_loaded()


def test_idle_check_skips_when_task_active(client, monkeypatch):
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", False)
    monkeypatch.setattr(main.asr, "_last_used", time.time() - 1000)
    main.tasks._tasks["t"] = {"status": "asr_running"}
    try:
        assert main._idle_check(60) is False
        assert main.asr.is_loaded()
    finally:
        main.tasks._tasks.clear()


def test_idle_watcher_loop_unloads(client, monkeypatch):
    """Full wiring: watcher task → _idle_check → unload_model, in a real loop."""
    import asyncio as _a
    main.tasks._tasks.clear()
    monkeypatch.setattr(main.asr, "_model", object())
    monkeypatch.setattr(main.asr, "_busy", False)
    monkeypatch.setattr(main.asr, "_last_used", time.time() - 1000)
    monkeypatch.setattr(main, "_WATCHER_TICK_S", 0.05)
    monkeypatch.setattr(main, "_idle_unload_seconds", lambda: 60)

    async def go():
        task = _a.create_task(main._idle_watcher())
        for _ in range(20):  # wait up to ~1s for the watcher to fire
            if not main.asr.is_loaded():
                task.cancel()
                break
            await _a.sleep(0.05)
        else:
            task.cancel()
        try:
            await task
        except _a.CancelledError:
            pass
    _a.run(go())
    assert not main.asr.is_loaded(), "watcher should have unloaded the model"
