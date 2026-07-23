#!/usr/bin/env python3
"""Hourly cron script: resume stuck meeting tasks.

Scans data/ for meetings whose status indicates work should be in progress but
which are not currently running in the service memory, then calls the resume
endpoint. Meetings already running are left alone.
"""

import json
import sys
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
DATA_DIR = Path("data")
BUSY_STATUSES = {"pending", "converting", "asr_running",
                 "llm_polishing", "llm_summarizing", "error"}


def api_call(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def main() -> int:
    if not DATA_DIR.exists():
        print("data dir not found")
        return 0

    # Quick health check.
    info = api_call("GET", "/api/info")
    if "_error" in info:
        print(f"service unreachable: {info['_error']}")
        return 1

    resumed = 0
    for mdir in DATA_DIR.iterdir():
        if not mdir.is_dir():
            continue
        meta_path = mdir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = meta.get("status")
        if status not in BUSY_STATUSES:
            continue
        meeting_id = meta.get("id") or mdir.name
        logs = api_call("GET", f"/api/meetings/{meeting_id}/logs")
        # If the service already has this in memory as running, skip.
        if logs.get("status") in BUSY_STATUSES and "_error" not in logs:
            # Wait — logs returns the stored status too; check /api/meetings to see if a task is active.
            # We rely on the resume endpoint itself to reject already-running tasks.
            pass
        result = api_call("POST", f"/api/meetings/{meeting_id}/resume")
        if result.get("ok"):
            print(f"resumed {meeting_id}: {result.get('action')} (was {status})")
            resumed += 1
        elif result.get("reason") == "already_running":
            print(f"skipping {meeting_id}: already running")
        else:
            print(f"no action for {meeting_id}: {result.get('reason')} ({status})")
    print(f"done: {resumed} resumed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
