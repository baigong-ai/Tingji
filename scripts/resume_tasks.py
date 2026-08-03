#!/usr/bin/env python3
"""Hourly cron script: resume stuck meeting tasks.

Scans the data dir for meetings whose status indicates work should be in
progress but which are not running in the service memory, then calls the
resume endpoint. Meetings already running are left alone (the endpoint
rejects them), meetings stuck in live_recording are marked as failed.

Port / SSL / data_dir are read from config.yaml — the same file the service
uses — so custom ports, HTTPS mode, and non-default data dirs all work.

Install (every hour at minute 17, adjust path to your checkout):

    crontab -l | { cat; echo '17 * * * * cd /path/to/Tingji && .venv/bin/python scripts/resume_tasks.py >> logs/resume.log 2>&1'; } | crontab -
"""

import json
import ssl
import sys
import urllib.request
from pathlib import Path

import yaml

CONFIG_PATH = Path("config.yaml")
BUSY_STATUSES = {"pending", "converting", "asr_running",
                 "llm_polishing", "llm_summarizing", "error"}

_SSL_CTX = None  # lazily created for https (self-signed cert)


def load_runtime() -> tuple[str, Path]:
    raw = {}
    if CONFIG_PATH.exists():
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    server = raw.get("server") or {}
    port = int(server.get("port") or 8000)
    use_ssl = bool((server.get("ssl") or {}).get("enabled"))
    data_dir = Path((raw.get("storage") or {}).get("data_dir") or "data").expanduser()
    scheme = "https" if use_ssl else "http"
    return f"{scheme}://127.0.0.1:{port}", data_dir


def api_call(base_url: str, method: str, path: str, data: dict | None = None) -> dict:
    global _SSL_CTX
    url = f"{base_url}{path}"
    body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"} if body else {})
    try:
        if url.startswith("https://"):
            # The service uses a self-signed LAN cert; verification would fail.
            if _SSL_CTX is None:
                _SSL_CTX = ssl.create_default_context()
                _SSL_CTX.check_hostname = False
                _SSL_CTX.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def main() -> int:
    base_url, data_dir = load_runtime()
    if not data_dir.exists():
        print(f"data dir not found: {data_dir}")
        return 0

    # Quick health check.
    info = api_call(base_url, "GET", "/api/info")
    if "_error" in info:
        print(f"service unreachable: {info['_error']}")
        return 1

    resumed = 0
    for mdir in data_dir.iterdir():
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
        result = api_call(base_url, "POST", f"/api/meetings/{meeting_id}/resume")
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
