import asyncio
from unittest import mock

import pytest

from app import storage, tasks


@pytest.fixture(autouse=True)
def reset_state():
    tasks._tasks.clear()
    tasks._lock = asyncio.Lock()
    yield
    tasks._tasks.clear()


def test_estimate_total_seconds():
    assert tasks.estimate_total_seconds(60 * 60 * 1000) == 900


def test_get_progress_unknown():
    assert tasks.get_progress("nope") is None


def test_register_task():
    state = tasks.register_task("mid-1")
    assert state["meeting_id"] == "mid-1"
    assert state["status"] == "pending"
    assert state["progress"] == 0
    assert tasks.get_progress(state["task_id"]) is not None


def test_advance_progress_caps_at_stage_end():
    state = tasks.register_task("mid-2")
    tasks.update(state["task_id"], status="asr_running", progress=10,
                 step="ASR", started_at=0, estimated_total_s=100)
    tasks.advance_asr_progress(state["task_id"], elapsed_s=10)
    p = tasks.get_progress(state["task_id"])["progress"]
    assert 5 <= p < 55


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return storage.DATA_DIR


def _make_meeting(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    return storage.create_meeting("t", str(src), "wav")


def test_append_log_persists_to_disk(data_dir):
    mid = _make_meeting(data_dir)
    tasks.append_log(mid, "info", "hello")
    assert any(l["msg"] == "hello" for l in storage.read_log_lines(mid))


def test_get_logs_reads_disk_when_not_in_memory(data_dir):
    mid = _make_meeting(data_dir)
    tasks.append_log(mid, "info", "cached")
    tasks._tasks.clear()  # simulate process restart
    out = tasks.get_logs(mid)
    assert out["logs"] and out["logs"][0]["msg"] == "cached"


def test_record_timing_and_summary(data_dir):
    mid = _make_meeting(data_dir)
    tasks._record_timing(mid, "convert", 3.1)
    tasks._record_timing(mid, "asr", 12.3)
    tasks._log_stage_summary(mid, "识别阶段完成", ("convert", "转换"), ("asr", "识别"))
    meta = storage.get_meeting(mid)["meta"]
    assert meta["timings"]["asr"] == 12.3
    assert "识别阶段完成" in storage.read_log_lines(mid)[-1]["msg"]
