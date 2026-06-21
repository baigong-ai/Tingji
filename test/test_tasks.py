import asyncio
from unittest import mock

import pytest

from app import tasks


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
