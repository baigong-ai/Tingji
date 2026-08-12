#!/usr/bin/env python3
"""Browser E2E smoke: drives a real (headless) Chromium against a live server.

Covers the v0.5 UI additions that unit tests can't reach:
  - detail page: edit & save the polished text (整理版) and the summary
  - detail page: resume button visible on error status
  - home page: trash dialog restore flow

Manual script (like smoke_asr.py / smoke_llm.py) — not part of pytest.
Requires: uv pip install playwright + a Chromium binary. Reuses the machine's
shared browser cache (~/Library/Caches/ms-playwright) via executable_path, so
no browser download is needed when the cache is populated.

Run:  .venv/bin/python test/smoke_browser.py
"""

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import storage  # noqa: E402

PORT = 8130
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = (Path.home() / "Library/Caches/ms-playwright"
            / "chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell")

PASS, FAIL = "✅", "❌"
failures = []


def check(name: str, cond: bool, extra: str = ""):
    print(f"{PASS if cond else FAIL} {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        failures.append(name)


def wait_server(timeout=20):
    for _ in range(timeout * 4):
        try:
            urllib.request.urlopen(f"{BASE}/api/info", timeout=2)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main() -> int:
    if not CHROMIUM.exists():
        print(f"chromium not found at {CHROMIUM}; run `playwright install chromium`")
        return 2

    # --- fixture meeting with polished text + structured summary ---
    src = Path("/tmp/smoke_browser.wav")
    src.write_bytes(b"x")
    mid = storage.create_meeting("浏览器冒烟", str(src), "wav")
    storage.save_raw(mid, {"text": "你好", "sentences": [
        {"start": 0, "end": 1000, "spk": 0, "text": "你好"}], "spk_count": 1})
    storage.save_processed(mid, "# 原始整理版\n\n内容")
    storage.save_summary_json(mid, {"summary": "原始概述", "decisions": ["决定甲"],
                                    "action_items": ["待办甲"], "open_questions": []})
    storage.save_summary(mid, "## 概述\n\n原始概述")
    storage.update_meta(mid, status="done", audio_wav="audio.wav")
    qmid = urllib.parse.quote(mid)  # meeting ids contain CJK — encode for urllib

    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_server():
            print("server did not start")
            return 2

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(CHROMIUM))
            page = browser.new_page()

            # ===== detail page: edit polished text =====
            page.goto(f"{BASE}/m/{qmid}")
            page.wait_for_selector('.tab-btn[data-tab="processed"]')
            page.click('.tab-btn[data-tab="processed"]')
            page.click("#proc-edit-btn")
            page.wait_for_selector("#proc-edit-text")
            page.fill("#proc-edit-text", "# 浏览器改过的整理版")
            page.click("#proc-edit-save")
            page.wait_for_selector("#proc-edit-btn", state="visible", timeout=8000)
            body = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid}").read())
            check("整理版编辑保存", body["processed"] == "# 浏览器改过的整理版",
                  repr(body["processed"]))

            # ===== detail page: edit structured summary =====
            page.click('.tab-btn[data-tab="summary"]')
            page.click("#sum-edit-btn")
            page.wait_for_selector("#sum-edit-summary")
            page.fill("#sum-edit-summary", "浏览器改过的概述")
            page.fill("#sum-edit-decisions", "决定甲\n决定乙")
            page.click("#sum-edit-save")
            page.wait_for_selector("#sum-edit-btn", state="visible", timeout=8000)
            body = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid}").read())
            sj = body["summary_json"] or {}
            check("总结结构化编辑保存",
                  sj.get("summary") == "浏览器改过的概述" and sj.get("decisions") == ["决定甲", "决定乙"],
                  repr(sj))
            check("总结 md 重新生成", "决定乙" in (body["summary"] or ""))

            # ===== S1: markdown link XSS sanitization =====
            # A poisoned summary/minutes could carry [x](javascript:...); the
            # render path (escapeHtml → marked.parse → sanitizeMdHtml) must strip
            # the dangerous protocol while keeping a normal https link intact.
            xss_md = ("## 概述\n\n"
                      "[恶意](javascript:alert(document.cookie)) 和 "
                      "[正常](https://example.com) 链接")
            storage.save_summary(mid, xss_md)
            storage.save_summary_json(mid, None)  # force markdown render path
            storage.update_meta(mid, status="done", error=None)
            page.reload()
            page.click('.tab-btn[data-tab="summary"]')
            page.wait_for_selector("#summary-md a", timeout=8000)
            hrefs = page.eval_on_selector_all(
                "#summary-md a", "els => els.map(e => e.getAttribute('href') || '')")
            check("XSS: javascript: 链接被去除",
                  not any(h.strip().lower().startswith(("javascript:", "vbscript:", "data:")) for h in hrefs),
                  repr(hrefs))
            check("XSS: 正常 https 链接保留", any(h == "https://example.com" for h in hrefs), repr(hrefs))

            # ===== resume button on error status =====
            storage.update_meta(mid, status="error", error="模拟失败")
            page.reload()
            page.wait_for_selector("#resume-btn", state="visible", timeout=8000)
            check("error 状态显示「恢复任务」按钮", page.is_visible("#resume-btn"))

            # ===== home page: trash dialog =====
            storage.update_meta(mid, status="done", error=None)
            # trash the meeting via API, then restore it from the UI
            req = urllib.request.Request(f"{BASE}/api/meetings/{qmid}?keep=1", method="DELETE")
            urllib.request.urlopen(req)
            page2 = browser.new_page()
            page2.goto(BASE)
            page2.click("#trash-btn")
            page2.wait_for_selector(".trash-item", timeout=8000)
            check("回收站弹窗列出已删会议", mid in page2.content())
            page2.click('.trash-item [data-act="restore"]')
            page2.wait_for_selector(".trash-item", state="detached", timeout=8000)
            items = json.loads(urllib.request.urlopen(f"{BASE}/api/trash").read())["items"]
            check("回收站恢复成功", all(i["name"] != mid for i in items))
            meetings = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings").read())
            check("恢复后回到历史列表", any(m["id"] == mid for m in meetings))

            browser.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        storage.delete_meeting(mid)
        # in case it ended up in trash
        storage.delete_from_trash(mid)

    print()
    if failures:
        print(f"FAILED: {len(failures)} — {failures}")
        return 1
    print("ALL BROWSER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
