# 测试

## 单元测试

```bash
uv pip install -e ".[dev]"
pytest -v
```

70 个测试覆盖 config / audio / storage / llm / asr / tasks / main 全部模块。其中 v0.2 新增覆盖：ASR 模型卸载（`unload_model` idle/busy/noop、`mark_used`、`status`）、端口冲突检测（空闲/占用/自身/非法）、服务设置 roundtrip + `restart_required`、idle watcher 决策（`_idle_check` 三种情形）+ 完整 asyncio 循环跑 `_idle_watcher` 的集成测试。

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
