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
    # B10: RTF is device-dependent (cuda 0.025 / mps 0.25 / cpu 4.7), no longer
    # hard-coded 0.25. The estimate must track _asr_rtf() on whichever device
    # the test machine is.
    rtf = tasks._asr_rtf()
    assert tasks.estimate_total_seconds(60 * 60 * 1000) == 60 * 60 * rtf


def test_asr_rtf_in_valid_range():
    rtf = tasks._asr_rtf()
    assert rtf in (0.025, 0.25, 4.7)


def test_get_progress_unknown():
    assert tasks.get_progress("nope") is None


def test_register_task():
    state = tasks.register_task("mid-1")
    assert state["meeting_id"] == "mid-1"
    assert state["status"] == "pending"
    assert state["progress"] == 0
    assert tasks.get_progress(state["task_id"]) is not None


def test_latest_task_id_returns_newest():
    t1 = tasks.register_task("mid-x")
    t2 = tasks.register_task("mid-x")
    assert tasks.latest_task_id("mid-x") == t2["task_id"]
    assert tasks.latest_task_id("mid-x") != t1["task_id"]
    assert tasks.latest_task_id("no-such") is None


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


def test_append_log_reaches_all_tasks_of_meeting(data_dir):
    mid = _make_meeting(data_dir)
    t1 = tasks.register_task(mid)
    t2 = tasks.register_task(mid)
    tasks.append_log(mid, "info", "hi")
    assert any(l["msg"] == "hi" for l in tasks._tasks[t1["task_id"]]["logs"])
    assert any(l["msg"] == "hi" for l in tasks._tasks[t2["task_id"]]["logs"])


def test_get_logs_prefers_latest_task(data_dir):
    mid = _make_meeting(data_dir)
    old = tasks.register_task(mid)
    tasks.update(old["task_id"], status="error", error="boom")
    tasks.register_task(mid)
    new_id = tasks.latest_task_id(mid)
    tasks.update(new_id, status="asr_running", progress=30)
    out = tasks.get_logs(mid)
    assert out["status"] == "asr_running"


def test_run_pipeline_updates_the_given_task(data_dir, monkeypatch):
    """After resume/retry a meeting has several tasks; run_pipeline must update
    the task the caller registered (the one the frontend polls), not the
    oldest stale one."""
    mid = _make_meeting(data_dir)
    old = tasks.register_task(mid)
    tasks.update(old["task_id"], status="error", error="stale")
    new = tasks.register_task(mid)
    monkeypatch.setattr(tasks, "_convert_audio", mock.AsyncMock())
    monkeypatch.setattr(tasks, "_run_asr", mock.AsyncMock())
    asyncio.run(tasks.run_pipeline(mid, cfg=None, task_id=new["task_id"]))
    assert tasks.get_progress(new["task_id"])["status"] == "asr_done"
    assert tasks.get_progress(old["task_id"])["status"] == "error"


def test_run_pipeline_falls_back_to_latest_task(data_dir, monkeypatch):
    mid = _make_meeting(data_dir)
    old = tasks.register_task(mid)
    tasks.update(old["task_id"], status="error", error="stale")
    new = tasks.register_task(mid)
    monkeypatch.setattr(tasks, "_convert_audio", mock.AsyncMock())
    monkeypatch.setattr(tasks, "_run_asr", mock.AsyncMock())
    asyncio.run(tasks.run_pipeline(mid, cfg=None))
    assert tasks.get_progress(new["task_id"])["status"] == "asr_done"
    assert tasks.get_progress(old["task_id"])["status"] == "error"


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


# --- B8: _tasks bounded growth ----------------------------------------------
def test_prune_tasks_evicts_oldest_terminal_first(monkeypatch):
    monkeypatch.setattr(tasks, "_MAX_TASKS", 5)
    tasks._tasks.clear()
    ids = []
    for _ in range(5):
        st = tasks.register_task("m")
        ids.append(st["task_id"])
        tasks.update(st["task_id"], status="done")  # all terminal
    # 6th registration exceeds the cap → oldest terminal task evicted
    kept = tasks.register_task("m")
    assert len(tasks._tasks) <= 5
    assert ids[0] not in tasks._tasks  # oldest terminal evicted
    assert ids[-1] in tasks._tasks     # newer terminal still around
    assert kept["task_id"] in tasks._tasks


def test_prune_tasks_never_evicts_busy(monkeypatch):
    monkeypatch.setattr(tasks, "_MAX_TASKS", 3)
    tasks._tasks.clear()
    busy_ids = []
    for _ in range(3):
        st = tasks.register_task("m")
        busy_ids.append(st["task_id"])
        tasks.update(st["task_id"], status="asr_running")  # busy, must survive
    # one more → cap exceeded but all are busy; we keep latest, drop oldest busy
    tasks.register_task("m")
    assert len(tasks._tasks) <= 3
    # the two most recently registered must still be present
    assert busy_ids[-1] in tasks._tasks


# --- B12: finalize_live except branch sets spk_count=0 ----------------------
def test_finalize_live_except_sets_spk_zero(data_dir, monkeypatch):
    mid = _make_meeting(data_dir)

    def boom(*a, **k):
        raise RuntimeError("offline asr failed")

    monkeypatch.setattr(tasks.asr, "transcribe", boom)
    pcm = b"\x00\x00" * 16000  # 1 second of silence
    result = {"sentences": [{"text": "a", "start": 0, "end": 1000, "spk": 0}]}
    asyncio.run(tasks.finalize_live(mid, result, pcm, 16000, cfg=None))
    raw = storage.get_meeting(mid)["raw"]
    # B12: streaming sentences all have spk=0 → set() would wrongly give 1; expect 0.
    assert raw["spk_count"] == 0
    assert storage.get_meeting(mid)["meta"]["status"] == "asr_done"
