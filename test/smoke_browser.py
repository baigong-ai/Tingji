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
        {"start": 0, "end": 1000, "spk": 0, "text": "你好"},
        {"start": 1100, "end": 2000, "spk": 1, "text": "世界"}], "spk_count": 2})
    storage.save_processed(mid, "# 原始整理版\n\n内容")
    storage.save_summary_json(mid, {"summary": "原始概述", "decisions": ["决定甲"],
                                    "action_items": ["待办甲"], "open_questions": []})
    storage.save_summary(mid, "## 概述\n\n原始概述")
    storage.update_meta(mid, status="done", audio_wav="audio.wav", spk_count=2)
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
                  sj.get("summary") == "浏览器改过的概述" and sj.get("decisions") == [{"text": "决定甲"}, {"text": "决定乙"}],
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

            # ===== P0.3: speaker merge (pure meta remap) + P1.1 export options =====
            storage.update_meta(mid, status="done", error=None)
            page.reload()
            page.wait_for_selector("#speakers-bar .spk-chip", timeout=8000)
            # export dropdown exposes the new docx / minutes options
            fmts = page.eval_on_selector_all(
                "#export-format option", "els => els.map(e => e.value)")
            check("导出下拉含 docx/minutes", "docx" in fmts and "minutes" in fmts, repr(fmts))
            # merge speaker 0 -> 1 (the bar has 2 chips; merge reduces to 1).
            # U4: merge confirm now uses the custom confirmDialog (#msg-modal), not native confirm().
            page.click("#merge-speakers-btn")
            page.click('#speakers-bar .spk-chip[data-spk="0"]')  # source (被并入)
            page.click('#speakers-bar .spk-chip[data-spk="1"]')   # target (保留) -> 弹 #msg-modal
            page.wait_for_selector("#msg-modal:not(.hidden)", timeout=8000)
            check("合并确认弹窗 #msg-modal 出现", page.is_visible("#msg-ok"))
            page.click("#msg-ok")
            page.wait_for_function(
                "() => document.querySelectorAll('#speakers-bar .spk-chip').length === 1",
                timeout=8000)
            sj = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid}").read())
            check("说话人合并后 spk_count=1", sj["meta"]["spk_count"] == 1, str(sj["meta"]["spk_count"]))
            # U4: 说话人改名走 promptDialog（#msg-modal 带 input）
            page.click('#speakers-bar .spk-chip')
            page.wait_for_selector("#msg-input", timeout=8000)
            page.fill("#msg-input", "张三")
            page.click("#msg-ok")
            page.wait_for_function(
                "() => document.getElementById('msg-modal').classList.contains('hidden')",
                timeout=8000)
            sj = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid}").read())
            check("promptDialog 改名生效", sj["meta"]["speaker_names"].get("0") == "张三",
                  str(sj["meta"].get("speaker_names")))

            # ===== resume button on error status =====
            storage.update_meta(mid, status="error", error="模拟失败")
            page.reload()
            page.wait_for_selector("#resume-btn", state="visible", timeout=8000)
            check("error 状态显示「恢复任务」按钮", page.is_visible("#resume-btn"))

            # ===== v0.7: 纪要时间戳 chip + 个人笔记 + 议题时间轴 =====
            from app import llm as _llm
            from datetime import datetime as _dt
            mid2 = storage.create_meeting("浏览器冒烟0.7", str(src), "wav")
            storage.save_raw(mid2, {"text": "你好 世界", "sentences": [
                {"start": 0, "end": 1000, "spk": 0, "text": "先对齐目标"},
                {"start": 1100, "end": 2000, "spk": 1, "text": "讨论预算"},
                {"start": 2100, "end": 3000, "spk": 1, "text": "预算要补问的句子"},
                {"start": 3100, "end": 4000, "spk": 0, "text": "确定方案"},
                {"start": 4100, "end": 5000, "spk": 0, "text": "分配任务"},
                {"start": 5100, "end": 5500, "spk": 1, "text": "散会"},
            ], "spk_count": 2})
            storage.save_processed(mid2, "# 整理版\n\n内容")
            sj2 = {"summary": "概述", "decisions": [{"text": "定了方案B", "ts": [3.1]}],
                   "action_items": [{"text": "张三跟进", "ts": [4.1]}], "open_questions": []}
            storage.save_summary_json(mid2, sj2)
            storage.save_summary(mid2, _llm.summary_to_md(_llm.clean_summary_json(sj2)))
            storage.save_topics(mid2, {"segments": [
                {"topic": "需求确认", "start": 0, "end": 3.0, "phase": "讨论"},
                {"topic": "收尾分工", "start": 3.0, "end": 5.5, "phase": "行动"},
            ], "manual": False})
            storage.save_notes(mid2, [{"id": "n1", "anchor": {"type": "sentence", "idx": 2},
                                       "text": "已有锚定笔记", "created_at": "2026-09-09T10:00:00",
                                       "updated_at": "2026-09-09T10:00:00"}])
            storage.update_meta(mid2, status="done", audio_wav="audio.wav", spk_count=2, duration_ms=5500)
            qmid2 = urllib.parse.quote(mid2)

            page.goto(f"{BASE}/m/{qmid2}")
            page.wait_for_selector('.tab-btn[data-tab="summary"]')
            page_errors = []
            page.on("pageerror", lambda e: page_errors.append(str(e)))

            # -- 3.1 纪要时间戳 chip：渲染 + 点击不报错 --
            page.click('.tab-btn[data-tab="summary"]')
            page.wait_for_selector("#summary-md .ts-chip", timeout=8000)
            chips = page.eval_on_selector_all("#summary-md .ts-chip",
                                              "els => els.map(e => e.dataset.sec)")
            check("纪要条目时间戳 chip 渲染", "3.1" in chips and "4.1" in chips, repr(chips))
            page.click("#summary-md .ts-chip")
            page.wait_for_timeout(300)
            check("时间戳 chip 点击无 JS 错误", not page_errors, repr(page_errors))

            # -- 总结编辑往返：行尾 [m:ss] 时间戳不丢 --
            page.click("#sum-edit-btn")
            page.wait_for_selector("#sum-edit-decisions")
            decisions_val = page.input_value("#sum-edit-decisions")
            check("编辑框带出时间戳", "定了方案B [0:03]" in decisions_val, repr(decisions_val))
            page.fill("#sum-edit-decisions", "改后的决议 [0:04]")
            page.click("#sum-edit-save")
            page.wait_for_selector("#sum-edit-btn", state="visible", timeout=8000)
            sj = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid2}").read())["summary_json"]
            check("编辑保存后 ts 解析回对象",
                  sj["decisions"] == [{"text": "改后的决议", "ts": [4.0]}], repr(sj["decisions"]))

            # -- 3.2 笔记：原文句入口 + 角标 --
            page.click('.tab-btn[data-tab="raw"]')
            page.wait_for_selector("#transcript .note-btn.has-notes", timeout=8000)
            badge = page.text_content('#transcript .transcript-line[data-idx="2"] .note-btn').strip()
            check("有笔记的句子显示角标", "1" in badge, repr(badge))
            page.click('#transcript .transcript-line[data-idx="0"] .note-btn')
            page.wait_for_selector("#note-modal:not(.hidden)", timeout=8000)
            check("笔记弹窗显示锚定句", "先对齐目标" in page.text_content("#note-modal-anchor"))
            page.fill("#note-text", "浏览器新增的锚定笔记")
            page.click("#note-save")
            page.wait_for_function(
                "() => document.querySelector('#transcript .transcript-line[data-idx=\"0\"] .note-btn') && document.querySelector('#transcript .transcript-line[data-idx=\"0\"] .note-btn').textContent.includes('1')",
                timeout=8000)
            notes = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid2}/notes").read())["notes"]
            check("锚定笔记落库", any(n["text"] == "浏览器新增的锚定笔记" and n["anchor"]["idx"] == 0 for n in notes),
                  repr(notes))

            # -- 3.2 笔记：总结 tab 折叠区（列表/跳转/编辑/删除/自由笔记）--
            page.click('.tab-btn[data-tab="summary"]')
            page.wait_for_selector("#notes-section:not(.hidden)", timeout=8000)
            page.click("#notes-toggle")  # 展开
            page.wait_for_selector("#notes-list:not(.hidden) .note-item", timeout=8000)
            items = page.eval_on_selector_all("#notes-list .note-item", "els => els.length")
            check("笔记列表渲染", items == 2, str(items))
            # 跳转：点第一条笔记（按锚定句时间排序，第一条锚定 idx=0）的时间 chip → 回原文 tab 且高亮
            page.click('#notes-list .note-item .ts-chip')
            page.wait_for_selector('#tab-raw.active', timeout=8000)
            check("点笔记时间戳跳回原文", page.eval_on_selector(
                "#tab-raw .transcript-line.active", "el => el.dataset.idx") == "0")
            # 编辑
            page.click('.tab-btn[data-tab="summary"]')
            page.click('#notes-list .note-item [data-act="edit"]')
            page.wait_for_selector("#note-modal:not(.hidden)", timeout=8000)
            page.fill("#note-text", "改过的笔记")
            page.click("#note-save")
            page.wait_for_function(
                "() => document.querySelector('#notes-list') && document.querySelector('#notes-list').textContent.includes('改过的笔记')",
                timeout=8000)
            # 自由笔记
            page.click("#note-add-free")
            page.wait_for_selector("#note-modal:not(.hidden)", timeout=8000)
            page.fill("#note-text", "全局自由笔记")
            page.click("#note-save")
            page.wait_for_function(
                "() => document.querySelector('#notes-list') && document.querySelector('#notes-list').textContent.includes('全局自由笔记')",
                timeout=8000)
            free_tags = page.eval_on_selector_all("#notes-list .note-free-tag", "els => els.length")
            check("自由笔记带「全局」标记", free_tags == 1, str(free_tags))
            # 删除（confirmDialog）
            page.click('#notes-list .note-item [data-act="del"]')
            page.wait_for_selector("#msg-modal:not(.hidden)", timeout=8000)
            page.click("#msg-ok")
            page.wait_for_function(
                "() => document.querySelectorAll('#notes-list .note-item').length === 2", timeout=8000)
            notes = json.loads(urllib.request.urlopen(f"{BASE}/api/meetings/{qmid2}/notes").read())["notes"]
            check("删除笔记生效", len(notes) == 2 and all(n["text"] != "改过的笔记" or n["anchor"] for n in notes),
                  repr(notes))

            # -- 3.3 议题时间轴：渲染/跳转/编辑/删除 --
            page.wait_for_selector("#topic-timeline .topic-seg", timeout=8000)
            segs = page.eval_on_selector_all("#topic-timeline .topic-seg", "els => els.length")
            check("议题时间轴渲染", segs == 2, str(segs))
            page.click("#topic-timeline .topic-seg")
            page.wait_for_selector('#tab-raw.active', timeout=8000)
            check("点议题段跳回原文", page.eval_on_selector(
                "#tab-raw .transcript-line.active", "el => el.dataset.idx") == "0")
            # 编辑态：改名保存
            page.click("#topic-edit-btn")
            page.click('#topic-timeline .topic-seg[data-i="0"]')
            page.wait_for_selector("#topic-modal:not(.hidden)", timeout=8000)
            page.fill("#topic-modal-name", "改名后的议题")
            page.click("#topic-modal-save")
            page.wait_for_function(
                "() => document.querySelector('#topic-timeline') && document.querySelector('#topic-timeline').textContent.includes('改名后的议题')",
                timeout=8000)
            t = storage.load_topics(mid2)
            check("议题编辑落库且标记 manual", t["manual"] is True and t["segments"][0]["topic"] == "改名后的议题",
                  repr(t))
            # 删除段（并入前段）
            page.click('#topic-timeline .topic-seg[data-i="1"]')
            page.wait_for_selector("#topic-modal:not(.hidden)", timeout=8000)
            page.click("#topic-modal-delete")
            page.wait_for_selector("#msg-modal:not(.hidden)", timeout=8000)
            page.click("#msg-ok")
            page.wait_for_function(
                "() => document.querySelectorAll('#topic-timeline .topic-seg').length === 1", timeout=8000)
            t = storage.load_topics(mid2)
            check("删段后时间并入前段", len(t["segments"]) == 1 and t["segments"][0]["end"] == 5.5, repr(t["segments"]))

            # -- v0.7 实时页：增强模式选择器已移除 --
            page3 = browser.new_page()
            page3.goto(f"{BASE}/live")
            page3.wait_for_selector("#live-start", timeout=8000)
            check("实时页无引擎选择器", page3.locator("#engine-picker").count() == 0)
            check("实时页开始按钮可用", page3.locator("#live-start").is_enabled())
            page3.close()

            check("0.7 全程无 JS 错误", not page_errors, repr(page_errors))
            storage.delete_meeting(mid2)
            storage.delete_from_trash(mid2)

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
            # 回收站可能残留历史测试会议，必须按 data-name 精确点这一条
            page2.click(f'.trash-item[data-name="{mid}"] [data-act="restore"]')
            page2.wait_for_selector(f'.trash-item[data-name="{mid}"]', state="detached", timeout=8000)
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
