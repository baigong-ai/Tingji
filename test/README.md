# 测试

## 单元测试

```bash
uv pip install -e ".[dev]"
pytest -v
```

100+ 个测试覆盖 config / audio / storage / llm / asr / tasks / main / stream 全部模块。其中 v0.2 新增覆盖：ASR 模型卸载（`unload_model` idle/busy/noop、`mark_used`、`status`）、端口冲突检测（空闲/占用/自身/非法）、服务设置 roundtrip + `restart_required`、idle watcher 决策（`_idle_check` 三种情形）+ 完整 asyncio 循环跑 `_idle_watcher` 的集成测试。v0.3 新增覆盖：会议标签设置与去重（`/api/meetings/{id}/tags`）、已处理会议重命名（`/api/meetings/{id}/title`）、删除二选一（移到 `data/回收站/` 保留文件 / 彻底删除）、回收站不被当作会议列出、onboard 标记 roundtrip。v0.4 的实时链路在 v0.5 补上覆盖：实时会议创建与录音落盘（`create_live_meeting` / `save_live_audio`）、流式引擎 `feed`/`finalize`（decode 与标点均走 worker 线程、事件循环不被阻塞、尾随文本锁定为最终句）。v0.5 新增覆盖：任务匹配（`latest_task_id`、`run_pipeline` 用调用方注册的 task_id）、meeting_id 白名单与 meta.json 原子写/容错、retry_llm 后台化、sidecar 门禁、回收站 list/restore/delete（含 `.N` 碰撞后缀还原）、整理版/总结编辑保存、`live_recording` 重启标记 error。仍未覆盖（需真实模型或 WS 客户端）：`finalize_live` 端到端、WebSocket 实时会话、`make_engine`。

## 冒烟脚本

需要真实模型/网络，手工运行：

### ASR

```bash
# 把一段音频放到 test/sample/test.wav（不放仓库）
uv run python test/smoke_asr.py test/sample/test.wav
```

验证：输出的 `data/smoke_raw.json` 包含 `sentences`，每条有 `text/start/end/spk`。

### LLM

```bash
export LLM_API_KEY=your-key
uv run python test/smoke_llm.py data/smoke_raw.json
```

验证：`data/smoke_processed.md` 含 `## 说话人 N` 分段；`summarize` 现输出 4 段 JSON（summary/decisions/action_items/open_questions），脚本把它渲染成 `data/smoke_summary.md`（`## 概述 / ## 决议 / ## 待办 / ## 待讨论`），模型偶尔不吐严格 JSON 时回退纯 markdown。

## 测试音频

由于版权，不放仓库。可用：
- 自己录一段 1-2 分钟多人对话
- 或下载公开会议录音（如播客片段）
