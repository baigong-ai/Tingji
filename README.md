# FunASR 本地会议转录系统

基于 [FunASR](https://github.com/modelscope/FunASR) 的多人会议录音转文字系统。

## 特性

- 说话人自动区分（基于 CAM++）
- 逐句时间戳
- LLM 整理口语化文字 + 生成会议纪要
- 支持 GLM / DeepSeek / 通义 / Kimi / OpenAI 等 OpenAI 兼容 API，也支持本地 Ollama
- Web 界面拖拽上传、历史回看
- 支持 wav / mp3 / m4a / aac / flac / ogg / opus
- 支持长音频（60-90 分钟）

## 环境要求

- macOS / Linux
- Python 3.11（用 uv 管理）
- [uv](https://github.com/astral-sh/uv)
- ffmpeg（macOS：`brew install ffmpeg`）
- 首次启动会下载约 3-4GB FunASR 模型

## 快速开始

```bash
git clone <repo> funasr
cd funasr
cp config.yaml.example config.yaml
cp .env.example .env  # 编辑 .env，填入 LLM_API_KEY（api 模式）
./run.sh
```

浏览器打开 `http://127.0.0.1:8000`。

## 配置说明

编辑 `config.yaml`：

| 字段 | 说明 |
|---|---|
| `asr.cache_dir` | FunASR 模型缓存目录，默认 `./models` |
| `asr.hub` | `ms` (ModelScope，默认) 或 `hf` |
| `llm.mode` | `api` 或 `ollama` |
| `llm.api.*` | OpenAI 兼容 API 配置（base_url / api_key / model） |
| `llm.ollama.*` | 本地 Ollama 配置 |
| `llm.polish_chunk_minutes` | 整理时分段时长（分钟），默认 6 |

`api_key` 用 `${LLM_API_KEY}` 占位，从环境变量读取。

## 使用 Ollama 本地模型

```bash
# 安装并启动 ollama
ollama pull qwen2.5:7b
ollama serve

# 修改 config.yaml: llm.mode: ollama
./run.sh
```

## 使用其他 LLM（示例）

**DeepSeek：**
```yaml
llm:
  mode: api
  api:
    base_url: "https://api.deepseek.com/v1"
    api_key: "${LLM_API_KEY}"
    model: "deepseek-chat"
```

**通义千问：**
```yaml
llm:
  mode: api
  api:
    base_url: "https://dashscope.aliyun.com/compatible-mode/v1"
    api_key: "${LLM_API_KEY}"
    model: "qwen-plus"
```

**OpenAI：**
```yaml
llm:
  mode: api
  api:
    base_url: "https://api.openai.com/v1"
    api_key: "${LLM_API_KEY}"
    model: "gpt-4o-mini"
```

## 使用流程

1. 启动后访问 `http://127.0.0.1:8000`
2. 拖入会议音频文件，填写标题，点"开始转录"
3. 等待 pipeline：音频转换 → 语音识别 → LLM 整理 → LLM 总结
4. 详情页提供 4 个视图：
   - **原文**：带说话人和时间戳，点击任意句跳转音频
   - **整理版**：去口语化的规范文字
   - **会议总结**：核心议题 / 决议 / 待办
   - **原文↔整理对照**：左右双栏，滚动联动
5. 顶部可导出 `.md` / `.txt` / `.srt`

## 长音频说明

- 60-90 分钟音频：FunASR VAD 自动切片 + Paraformer 分批推理
- M4 16GB 估算耗时：音频时长 × 0.25（例：60 分钟音频约 15 分钟处理）
- 进度条为估算，ASR 阶段无精确回调

## 已知限制

- 说话人分离基于音色聚类，可能因设备/位置变化拆分或合并 ID
- LLM 整理可能轻微改变原意，对照视图可用于核对
- 无用户认证，仅适合本地运行
- 进行中的任务状态保存在内存，重启服务会丢失（已完成会议数据在磁盘上）

## 项目结构

```
app/
  config.py    配置加载（${ENV_VAR} 展开）
  audio.py     ffmpeg 转换 wrapper
  asr.py       FunASR AutoModel 单例封装
  llm.py       polish + summarize（分段 + map-reduce）
  storage.py   data/ 目录 CRUD
  tasks.py     异步 pipeline + 进度估算
  main.py      FastAPI 路由
static/
  index.html   首页（上传 + 历史）
  meeting.html 详情页（4 Tab）
  app.js       首页交互
  style.css    样式
data/          会议数据（gitignore）
models/        FunASR 模型缓存（gitignore）
test/          单元测试 + 冒烟脚本
```

## License

MIT
