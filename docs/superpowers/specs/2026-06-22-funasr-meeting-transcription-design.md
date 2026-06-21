# FunASR 本地会议转录系统 — 设计文档

- 日期：2026-06-22
- 状态：待评审
- 目标：本地部署一个基于 FunASR 的多人会议录音转文字系统，支持说话人区分、时间戳、LLM 整理与总结，提供 Web 界面。

## 1. 背景与目标

### 1.1 用户需求

1. 区分说话人
2. 带时间戳的逐句转录
3. 用大语言模型整理口语化文字（去口头禅、理顺语句、保留说话人）并生成会议纪要
4. 支持配置不同 LLM（GLM、DeepSeek、Qwen 等 OpenAI 兼容服务，或本地 Ollama）
5. 能简单实现就不要复杂化

### 1.2 运行环境

- Apple M4 / 16GB / macOS
- 已装：uv、Python 3.14（项目将用 uv 强制 3.11）
- 需补装：ffmpeg（`brew install ffmpeg`）

### 1.3 范围与非目标

- **在范围内**：本地 Web 网页、文件上传、异步转录、说话人分离、时间戳、LLM 整理+总结、原文↔整理对照视图、历史会议回看、导出
- **非目标**：实时麦克风转录、用户认证、多用户、限流、公网部署、模型加密

## 2. 总体架构

**技术选型**：

| 层 | 选型 | 理由 |
|---|---|---|
| ASR | FunASR `AutoModel`（paraformer-zh + fsmn-vad + ct-punc + cam++） | 官方一体化方案，自带说话人+时间戳+VAD |
| 模型源 | ModelScope（国内直连） | FunASR 默认，无需代理 |
| 后端 | FastAPI + uvicorn | 轻量，异步友好 |
| LLM 调用 | `openai` Python 库 | 一套协议兼容 API/Ollama |
| 前端 | 原生 HTML/CSS/JS | 无构建步骤，UI 完全可控 |
| 存储 | 文件系统（`data/` 目录） | 轻量，无数据库 |
| 任务 | FastAPI `BackgroundTasks` + 内存任务表 | 本地单用户够用 |

## 3. 目录结构

```
funasr/
├── README.md
├── pyproject.toml                 # uv 管理，Python 3.11
├── config.yaml                    # LLM + ASR 配置
├── run.sh                         # 启动脚本（设环境变量 + uvicorn）
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 路由
│   ├── config.py                  # 读 config.yaml，dataclass
│   ├── audio.py                   # ffmpeg 转换、读取时长
│   ├── asr.py                     # FunASR 封装：单例 AutoModel + transcribe()
│   ├── llm.py                     # polish() + summarize()，openai 库
│   ├── storage.py                 # data/ 目录 CRUD
│   └── tasks.py                   # 内存任务表 + pipeline
├── static/
│   ├── index.html                 # 首页：上传 + 历史
│   ├── meeting.html               # 详情页：4 Tab
│   ├── app.js
│   └── style.css
├── data/                          # 运行时数据，gitignore
│   └── {YYYYMMDD-HHMMSS}-{title}/
│       ├── meta.json
│       ├── audio.{ext}            # 原始上传
│       ├── audio_wav.wav          # 转换后给 ASR
│       ├── raw.json               # FunASR 输出
│       ├── processed_chunks/      # 分段 LLM 中间产物
│       │   ├── 0001.md
│       │   └── ...
│       ├── processed.md           # 整理版（合并）
│       └── summary.md             # 会议纪要
├── models/                        # FunASR 模型缓存，gitignore
├── test/
│   ├── smoke_asr.py
│   ├── smoke_llm.py
│   ├── sample/                  # 测试音频（不放仓库，README 指引用方自备）
│   └── README.md
└── docs/
    └── superpowers/specs/
        └── 2026-06-22-funasr-meeting-transcription-design.md
```

## 4. 组件职责

### 4.1 `app/config.py`

读 `config.yaml`，返回 dataclass：

```python
@dataclass
class ASRConfig:
    cache_dir: str
    hub: str                    # "ms" | "hf"
    batch_size_s: int           # 默认 300
    batch_size_threshold_s: int # 默认 60
    hotword: str                # 可选

@dataclass
class LLMConfig:
    mode: str                   # "api" | "ollama"
    api: APIConfig              # base_url, api_key, model
    ollama: OllamaConfig
    polish_chunk_minutes: int   # 默认 6
    temperature: float
    max_retries: int            # 默认 2

@dataclass
class Config:
    asr: ASRConfig
    llm: LLMConfig
    server: ServerConfig
```

- `${ENV_VAR}` 语法支持从环境变量读取敏感值
- `api_key` 永远不写死，从 `LLM_API_KEY` 等环境变量读

### 4.2 `app/audio.py`

- `convert_to_wav(src_path, dst_path)`：调用 ffmpeg 转 16kHz mono pcm_s16le
- `get_duration(path)`：ffprobe 读取时长（毫秒）
- `ensure_ffmpeg()`：启动时检查，未装则提示退出

### 4.3 `app/asr.py`

单例 `AutoModel`，启动时加载一次：

```python
_model = None

def get_model() -> AutoModel:
    global _model
    if _model is None:
        os.environ["FUNASR_HUB"] = cfg.asr.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.asr.cache_dir
        _model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            vad_revision="v2.0.4",
            punc_model="ct-punc",
            spk_model="cam++",
        )
    return _model

def transcribe(wav_path: str) -> dict:
    res = get_model().generate(
        audio=wav_path,
        batch_size_s=cfg.asr.batch_size_s,
        batch_size_threshold_s=cfg.asr.batch_size_threshold_s,
        sentence_timestamp=True,
        hotword=cfg.asr.hotword,
    )
    return normalize(res)       # 统一为 raw.json 结构
```

**输出归一化**（`raw.json`）：

```json
{
  "text": "全文合并纯文本",
  "sentences": [
    {"text": "...", "start": 0, "end": 3280, "spk": 0}
  ],
  "spk_count": 2
}
```

### 4.4 `app/llm.py`

```python
def _client() -> openai.OpenAI:
    if cfg.llm.mode == "api":
        return openai.OpenAI(
            base_url=cfg.llm.api.base_url,
            api_key=cfg.llm.api.api_key,
        )
    else:
        return openai.OpenAI(
            base_url=cfg.llm.ollama.base_url,
            api_key=cfg.llm.ollama.api_key,
        )

def polish(sentences: list[dict]) -> str:
    """分段整理，合并为 processed.md"""
    chunks = _chunk_sentences(sentences, minutes=cfg.llm.polish_chunk_minutes)
    outputs = []
    for i, chunk in enumerate(chunks):
        prompt = POLISH_PROMPT.format(input=_format_chunk(chunk))
        try:
            md = _chat(prompt, model=_model_name())
            outputs.append(md)
        except Exception:
            # 重试 max_retries 次后仍失败，保留原文并打标
            outputs.append(_format_chunk(chunk, mark_failed=True))
    return "\n\n---\n\n".join(outputs)

def summarize(processed_md: str) -> str:
    """生成会议纪要；超长则 map-reduce"""
    if len(processed_md) < 8000:
        return _chat(SUMMARIZE_PROMPT.format(input=processed_md), ...)
    else:
        chunks = _split_text(processed_md, size=6000)
        partial = [_chat(SUMMARIZE_PROMPT.format(input=c), ...) for c in chunks]
        return _chat(REDUCE_PROMPT.format(input="\n\n".join(partial)), ...)
```

**Prompts**（简要说明，实际代码内嵌）：

- `POLISH_PROMPT`：要求保留说话人标签 `## 说话人 N`，去除"那个/然后/嗯"等口头禅和重复，理顺句子，不擅自合并不同说话人内容，不添加虚构信息
- `SUMMARIZE_PROMPT`：输出 `## 核心议题 / ## 决议 / ## 待办` 三段，待办要带负责人
- `REDUCE_PROMPT`：把多个摘要合并成统一的会议纪要

### 4.5 `app/storage.py`

```python
def create_meeting(title: str, audio_path: str, ext: str) -> str
def list_meetings() -> list[dict]
def get_meeting(meeting_id: str) -> dict | None
def save_raw(meeting_id: str, raw: dict)
def save_processed(meeting_id: str, md: str)
def save_summary(meeting_id: str, md: str)
def update_meta(meeting_id: str, **fields)
def delete_meeting(meeting_id: str)
```

- 会议 ID 格式：`{YYYYMMDD-HHMMSS}-{slug(title)}`
- `list_meetings()` 按创建时间倒序
- `get_meeting()` 返回 `{meta, raw, processed, summary, audio_url}`

### 4.6 `app/tasks.py`

```python
_tasks: dict[str, TaskState] = {}      # 进程内
_lock = asyncio.Lock()                  # 保证 ASR 串行

@dataclass
class TaskState:
    meeting_id: str
    status: str                          # pending|converting|asr_running|llm_polishing|llm_summarizing|done|error
    progress: int                        # 0-100
    step: str                            # 人类可读说明
    error: str | None
    started_at: float
    estimated_total_s: float             # 预估总耗时

async def run_pipeline(meeting_id: str):
    async with _lock:
        try:
            # _convert_audio 调用 app.audio.convert_to_wav
            _convert_audio(meeting_id)        # 0→5%
            await _run_asr(meeting_id)         # 5→55%, 调 app.asr.transcribe
            await _run_polish(meeting_id)      # 55→85%, 调 app.llm.polish
            await _run_summarize(meeting_id)   # 85→100%, 调 app.llm.summarize
            storage.update_meta(meeting_id, status="done")
        except Exception as e:
            storage.update_meta(meeting_id, status="error", error=str(e))

def get_progress(task_id: str) -> dict
```

**进度估算策略**：

| 阶段 | 进度区间 | 推进方式 |
|---|---|---|
| 音频转换 | 0 → 5 | ffmpeg 完成 |
| ASR 推理 | 5 → 55 | 按已耗时 / 预估总耗时线性推进（预估总耗时 = 音频时长 × 0.25），封顶 50；ASR 真正完成时跳 55 |
| LLM polish | 55 → 85 | 已完成 chunk 数 / 总 chunk 数 |
| LLM summarize | 85 → 98 | 假进度；完成跳 100 |

预估速率 0.25（音频时长 / ASR 耗时）在 M4 CPU 跑 Paraformer 的经验值，MPS 加速后更快，但保守估算无妨。

## 5. API 设计

| 方法 | 路径 | 入参 | 返回 |
|---|---|---|---|
| GET | `/` | — | 首页 HTML |
| GET | `/m/{id}` | — | 详情页 HTML |
| POST | `/api/upload` | multipart: `audio`, `title` | `{task_id, meeting_id}` |
| GET | `/api/tasks/{task_id}` | — | `{status, progress, step, error}` |
| GET | `/api/meetings` | — | `[{id, title, created_at, status, duration_ms, spk_count}]` |
| GET | `/api/meetings/{id}` | — | `{meta, raw, processed, summary}` |
| GET | `/api/meetings/{id}/audio` | — | 音频文件流 |
| GET | `/api/meetings/{id}/export?format=md\|txt\|srt` | — | 下载文件 |
| POST | `/api/meetings/{id}/retry-llm` | — | `{task_id}` |
| DELETE | `/api/meetings/{id}` | — | `{ok: true}` |

## 6. 数据结构

### 6.1 `meta.json`

```json
{
  "id": "20260622-143022-产品周会",
  "title": "产品周会",
  "created_at": "2026-06-22T14:30:22",
  "audio_file": "audio.m4a",
  "audio_wav": "audio_wav.wav",
  "duration_ms": 3650000,
  "status": "done",
  "spk_count": 2,
  "error": null
}
```

### 6.2 `raw.json`

见 §4.3 输出归一化。

### 6.3 `processed.md`

```markdown
## 说话人 1
今天我们讨论一下产品发布。下周三正式上线，需要准备公告和推送。

---

## 说话人 2
好的，我同意。我会负责推送文案，明天给你初稿。
```

（分段多时，chunk 之间用 `---` 分隔）

### 6.4 `summary.md`

```markdown
## 核心议题
- 产品发布时间定在下周三上线

## 决议
- 推送文案由说话人 2 负责起草

## 待办
- [ ] 明天推送文案初稿（说话人 2）
```

## 7. 前端页面

### 7.1 `index.html`（首页）

- 顶部：拖拽上传区 + 会议标题输入 + 开始按钮
- 中部：任务进行时显示进度条（`进度% · 步骤说明`）
- 底部：历史会议列表，点击进入详情页

### 7.2 `meeting.html`（详情页）

- 顶栏：返回 / 标题 / 时间 / 时长 / 人数 / 导出下拉
- 中部：4 个 Tab
  - **原文**：列表，每行 `[mm:ss] 说话人N  文本`，点击行跳转音频播放
  - **整理版**：渲染 `processed.md`
  - **会议总结**：渲染 `summary.md`
  - **原文↔整理对照**：左右双栏，滚动联动
- 底栏：固定 `<audio>` 播放器

### 7.3 交互细节

- 上传后获得 `task_id`，每 2 秒 `GET /api/tasks/{task_id}` 轮询
- 状态变 `done` 自动跳转详情页；`error` 显示错误并保留上传的会议条目
- 详情页"重试 LLM"按钮 → `POST /api/meetings/{id}/retry-llm`，复用 `raw.json` 重跑 polish+summarize

## 8. 配置文件

`config.yaml`：

```yaml
asr:
  cache_dir: "./models"              # 默认项目下；可改为绝对路径
  hub: "ms"                           # ModelScope (国内默认)，备选 "hf"
  batch_size_s: 300                   # 每批最多 300 秒，避免 OOM
  batch_size_threshold_s: 60          # VAD 单段上限
  hotword: ""                         # 可选热词，逗号分隔

llm:
  mode: api                           # api | ollama
  api:
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    api_key: "${LLM_API_KEY}"         # 从环境变量读
    model: "glm-4-flash"
  ollama:
    base_url: "http://localhost:11434/v1"
    model: "qwen2.5:7b"
    api_key: "ollama"                 # 占位
  polish_chunk_minutes: 6
  temperature: 0.3
  max_retries: 2

server:
  host: "127.0.0.1"
  port: 8000
```

`run.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# 检查环境
command -v ffmpeg >/dev/null || { echo "需要先安装 ffmpeg: brew install ffmpeg"; exit 1; }
[ -f .venv/bin/activate ] || uv venv --python 3.11

source .venv/bin/activate
uv pip install -e .

# 检查 LLM key（api 模式）
if grep -q 'mode: api' config.yaml && [ -z "${LLM_API_KEY:-}" ]; then
  echo "提示：LLM_API_KEY 未设置，LLM 功能将不可用"
fi

exec uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 9. 错误处理

| 错误 | 处理 |
|---|---|
| ffmpeg 未安装 | 启动脚本检测，直接退出提示安装 |
| 上传不是音频 | `POST /api/upload` 返回 415，前端红色提示 |
| 音频损坏 / ffmpeg 转换失败 | 任务 status=error，meta.error 记录原因 |
| FunASR 模型下载失败 | 启动时失败，提示检查网络/`cache_dir` 权限 |
| LLM 单 chunk 调用失败 | 重试 `max_retries` 次，仍失败保留原文并标 `[整理失败]`，不阻塞其他 chunk |
| LLM 整体失败 | status=error，详情页显示"重试 LLM"按钮，复用 `raw.json` |
| ASR 运行超 30 分钟 | 不拦截，前端显示已运行时长；用户可关闭浏览器，后台继续；若服务重启则进行中任务丢失 |
| 并发上传多个 | `asyncio.Lock` 串行执行 ASR（AutoModel 非线程安全） |

## 10. 长音频与多格式支持

### 10.1 长音频（60-90 分钟）

- **VAD 自动切片**：`fsmn-vad v2.0.4` 支持长音频，自动切为数百个短段
- **Paraformer 分批推理**：`batch_size_s=300`，每批最多 300 秒，避免 M4 16GB OOM
- **预估耗时**：60-90 分钟音频 ASR 约 8-25 分钟（视 CPU/MPS 加速）
- **LLM 分段**：原文按 `polish_chunk_minutes=6` 切片，每片 2000-3000 字，单独 polish 后合并

### 10.2 多格式支持

通过 ffmpeg 统一转 16kHz mono pcm_s16le wav，支持的输入格式：

- 音频：wav / mp3 / m4a / aac / flac / ogg / opus / webm
- 视频（仅取音轨）：mp4 / mov / mkv（README 提一下，不做重点宣传）

原文件保留在 `data/{id}/audio.{ext}`，转换后的 wav 单独存放。

## 11. 模型管理

- **默认源**：ModelScope（`hub: ms`），国内直连无代理
- **默认路径**：项目下 `./models`
- **自定义路径**：修改 `config.yaml` 的 `asr.cache_dir`
- **离线场景**：`cache_dir` 指向已下好模型的目录即可，FunASR 优先用本地缓存
- **首次启动**：下载约 3-4GB（paraformer-zh + fsmn-vad + ct-punc + cam++）

## 12. 测试策略

不引入单元测试框架（遵循"简单"原则）。提供冒烟脚本：

```
test/
├── smoke_asr.py       # 30s 测试音频 → 验证 raw.json 结构与字段
├── smoke_llm.py       # 假造 raw.json → 验证 polish/summarize 产出非空、含必要小节
└── README.md          # 如何跑冒烟、如何找测试音频
```

**手工验收清单**（写入项目 README）：

1. `./run.sh` 启动，浏览器打开 `http://127.0.0.1:8000`
2. 上传一段 10 分钟真实会议音频，等 pipeline 完成
3. 检查原文：说话人区分正确、时间戳与音频对齐
4. 检查整理版：口语化明显减少、保留说话人分段
5. 检查总结：核心议题/决议/待办齐全
6. 检查对照视图：左右滚动联动正常
7. 刷新首页：历史列表出现，可点击回看
8. 删除会议：目录与列表同步清除
9. 长音频回归：上传一段 60 分钟音频，观察内存占用与进度推进
10. 格式回归：分别上传 m4a、mp3、flac，均能正常处理

## 13. 部署与使用

### 13.1 安装

```bash
git clone <repo> funasr
cd funasr
brew install ffmpeg              # macOS
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .
```

### 13.2 配置 LLM

编辑 `config.yaml`，选择 `mode: api` 或 `mode: ollama`。

API 模式：

```bash
export LLM_API_KEY="你的 key"
./run.sh
```

Ollama 模式：

```bash
# 先装并启动 ollama，拉模型
ollama pull qwen2.5:7b
ollama serve
# 另开终端
./run.sh
```

### 13.3 首次启动

首次会下载 FunASR 模型约 3-4GB 到 `./models`，后续启动直接加载。

## 14. 已知限制

1. 说话人分离基于音色聚类，**同一个说话人中途换位置/换设备可能被拆成两个 ID**；不同人音色相近可能合并。这是 CAM++ 的固有局限。
2. LLM 整理可能**轻微改变原意**，对照视图可用于核对。
3. **无用户认证**，仅适合本地运行；若要公网部署需自行加反向代理鉴权。
4. 进度条为估算值，ASR 阶段（FunASR 无回调）尤其不准。
5. 任务状态保存在内存，**重启服务会丢失进行中的任务**（已完成会议数据在磁盘上，不受影响）。

## 15. 后续可扩展点（本期不做）

- 实时麦克风转录（需要 funasr websocket 服务，复杂度翻倍）
- 多用户/团队（加鉴权 + 数据库）
- 热词词典管理 UI
- 自定义 prompt 模板编辑
- 导出 docx/pdf
- 音频波形可视化 + 时间戳点击
