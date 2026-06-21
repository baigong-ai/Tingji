# FunASR 会议转录系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 macOS M4 本地部署一个 Web 会议转录系统：上传音频 → FunASR 转写（说话人+时间戳）→ LLM 整理 + 总结 → 历史回看。

**Architecture:** FastAPI 单进程后端 + 原生 HTML 前端；FunASR `AutoModel` 单例；LLM 通过 `openai` 库统一调用 API/Ollama；文件系统存储；BackgroundTasks + asyncio.Lock 串行 pipeline。

**Tech Stack:** Python 3.11（uv 管理）、FastAPI、FunASR、openai SDK、ffmpeg、原生 HTML/CSS/JS。

**Spec:** `docs/superpowers/specs/2026-06-22-funasr-meeting-transcription-design.md`

---

## File Structure

**后端（`app/`）：**
- `app/__init__.py` — 空
- `app/config.py` — `load_config()` 返回 `Config` dataclass
- `app/audio.py` — `convert_to_wav()` / `get_duration_ms()` / `ensure_ffmpeg()`
- `app/asr.py` — `get_model()` 单例 / `transcribe(wav_path) -> dict`
- `app/llm.py` — `_client()` / `polish(sentences) -> md` / `summarize(md) -> md`
- `app/storage.py` — 会议目录 CRUD：`create / list / get / save_* / update_meta / delete`
- `app/tasks.py` — `run_pipeline(meeting_id)` / `get_progress(task_id)` / 任务表
- `app/main.py` — FastAPI 应用与全部路由

**前端（`static/`）：**
- `static/index.html` — 上传 + 历史列表
- `static/meeting.html` — 详情页（4 Tab + 音频播放器）
- `static/app.js` — 交互逻辑
- `static/style.css` — 样式

**根目录：**
- `pyproject.toml` — uv 项目
- `config.yaml.example` — 配置模板
- `run.sh` — 启动脚本
- `README.md` — 使用说明
- `test/smoke_asr.py` / `test/smoke_llm.py` — 冒烟脚本

**测试策略：**
- 纯函数（config 解析、chunking、map-reduce 判断、进度估算）：pytest 单元测试
- 外部依赖（ASR、LLM、ffmpeg、FastAPI 路由）：mock 单元测试 + 手工冒烟脚本
- 用户全局指令偏好简洁，不做冗余集成测试

---

## Task 1: 项目骨架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `config.yaml.example`
- Create: `test/__init__.py`

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "funasr-meeting"
version = "0.1.0"
description = "Local meeting transcription system with FunASR"
requires-python = ">=3.11,<3.13"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "python-multipart>=0.0.9",
    "funasr>=1.1",
    "openai>=1.30",
    "pyyaml>=6.0",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

- [ ] **Step 2: 写 `app/__init__.py`（空文件）和 `test/__init__.py`（空文件）**

```bash
touch app/__init__.py test/__init__.py
```

- [ ] **Step 3: 写 `config.yaml.example`**

```yaml
asr:
  cache_dir: "./models"
  hub: "ms"
  batch_size_s: 300
  batch_size_threshold_s: 60
  hotword: ""

llm:
  mode: api
  api:
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    api_key: "${LLM_API_KEY}"
    model: "glm-4-flash"
  ollama:
    base_url: "http://localhost:11434/v1"
    model: "qwen2.5:7b"
    api_key: "ollama"
  polish_chunk_minutes: 6
  temperature: 0.3
  max_retries: 2

server:
  host: "127.0.0.1"
  port: 8000
```

- [ ] **Step 4: 建 uv venv 并安装**

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

预期：安装成功，`python -c "import fastapi; import funasr; import openai"` 不报错。

- [ ] **Step 5: 创建 .gitignore 已在 spec 阶段完成，跳过**

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/__init__.py test/__init__.py config.yaml.example
git commit -m "feat: project skeleton with deps"
```

---

## Task 2: 配置加载 `app/config.py`

**Files:**
- Create: `app/config.py`
- Create: `test/test_config.py`

- [ ] **Step 1: 写失败测试 `test/test_config.py`**

```python
import os
from app.config import load_config

def test_load_config_basic(tmp_path):
    yaml_text = """
asr:
  cache_dir: "./models"
  hub: "ms"
  batch_size_s: 300
  batch_size_threshold_s: 60
  hotword: ""
llm:
  mode: api
  api:
    base_url: "http://x/v1"
    api_key: "${MY_KEY}"
    model: "gpt-x"
  ollama:
    base_url: "http://localhost:11434/v1"
    model: "qwen2.5:7b"
    api_key: "ollama"
  polish_chunk_minutes: 6
  temperature: 0.3
  max_retries: 2
server:
  host: "127.0.0.1"
  port: 8000
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    os.environ["MY_KEY"] = "secret123"
    cfg = load_config(str(cfg_path))
    assert cfg.asr.cache_dir == "./models"
    assert cfg.llm.mode == "api"
    assert cfg.llm.api.api_key == "secret123"
    assert cfg.llm.polish_chunk_minutes == 6
    assert cfg.server.port == 8000

def test_load_config_missing_file():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_config.py -v
```

预期：FAIL（`ModuleNotFoundError: app.config`）

- [ ] **Step 3: 写 `app/config.py`**

```python
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass
class APIConfig:
    base_url: str
    api_key: str
    model: str


@dataclass
class OllamaConfig:
    base_url: str
    model: str
    api_key: str


@dataclass
class LLMConfig:
    mode: str
    api: APIConfig
    ollama: OllamaConfig
    polish_chunk_minutes: int
    temperature: float
    max_retries: int


@dataclass
class ASRConfig:
    cache_dir: str
    hub: str
    batch_size_s: int
    batch_size_threshold_s: int
    hotword: str


@dataclass
class ServerConfig:
    host: str
    port: int


@dataclass
class Config:
    asr: ASRConfig
    llm: LLMConfig
    server: ServerConfig


def _expand_env(value):
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {path}")
    raw = yaml.safe_load(p.read_text())
    raw = _expand_env(raw)
    return Config(
        asr=ASRConfig(**raw["asr"]),
        llm=LLMConfig(
            mode=raw["llm"]["mode"],
            api=APIConfig(**raw["llm"]["api"]),
            ollama=OllamaConfig(**raw["llm"]["ollama"]),
            polish_chunk_minutes=raw["llm"]["polish_chunk_minutes"],
            temperature=raw["llm"]["temperature"],
            max_retries=raw["llm"]["max_retries"],
        ),
        server=ServerConfig(**raw["server"]),
    )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_config.py -v
```

预期：2 passed

- [ ] **Step 5: Commit**

```bash
git add app/config.py test/test_config.py
git commit -m "feat(config): yaml loader with env var expansion"
```

---

## Task 3: 音频处理 `app/audio.py`

**Files:**
- Create: `app/audio.py`
- Create: `test/test_audio.py`

- [ ] **Step 1: 写失败测试 `test/test_audio.py`**

```python
import json
import subprocess
from unittest import mock
from pathlib import Path

import pytest

from app import audio


def test_ensure_ffmpeg_present():
    with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        audio.ensure_ffmpeg()  # should not raise


def test_ensure_ffmpeg_missing():
    with mock.patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg"):
            audio.ensure_ffmpeg()


def test_convert_to_wav_invokes_ffmpeg(tmp_path):
    src = tmp_path / "in.m4a"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.wav"
    with mock.patch("app.audio.ensure_ffmpeg"), \
         mock.patch("subprocess.run") as run:
        audio.convert_to_wav(str(src), str(dst))
    assert run.called
    args = run.call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "-ar" in args and "16000" in args
    assert "-ac" in args and "1" in args
    assert str(src) in args and str(dst) in args


def test_get_duration_ms(tmp_path):
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.MagicMock(
            stdout=json.dumps({"streams": [{"duration": "65.5"}]})
        )
        ms = audio.get_duration_ms(str(tmp_path / "x.wav"))
    assert ms == 65500
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_audio.py -v
```

预期：FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `app/audio.py`**

```python
import json
import shutil
import subprocess
from pathlib import Path


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffmpeg/ffprobe not found. Install via: brew install ffmpeg"
        )


def convert_to_wav(src: str, dst: str) -> None:
    ensure_ffmpeg()
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def get_duration_ms(path: str) -> int:
    ensure_ffmpeg()
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", path,
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    info = json.loads(out)
    duration_s = float(info["streams"][0]["duration"])
    return int(duration_s * 1000)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_audio.py -v
```

预期：4 passed

- [ ] **Step 5: Commit**

```bash
git add app/audio.py test/test_audio.py
git commit -m "feat(audio): ffmpeg wrapper for format conversion and duration"
```

---

## Task 4: 存储 `app/storage.py`

**Files:**
- Create: `app/storage.py`
- Create: `test/test_storage.py`

- [ ] **Step 1: 写失败测试 `test/test_storage.py`**

```python
import json
from pathlib import Path
from datetime import datetime

import pytest

from app import storage


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return storage.DATA_DIR


def test_create_meeting(data_dir):
    src = data_dir.parent / "src.m4a"
    src.write_bytes(b"audio-bytes")
    mid = storage.create_meeting(title="产品 周会", audio_path=str(src), ext="m4a")
    mdir = data_dir / mid
    assert mdir.exists()
    assert (mdir / "audio.m4a").exists()
    meta = json.loads((mdir / "meta.json").read_text())
    assert meta["title"] == "产品 周会"
    assert meta["status"] == "pending"
    assert meta["audio_file"] == "audio.m4a"


def test_list_meetings_sorted(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    m1 = storage.create_meeting("old", str(src), "wav")
    m2 = storage.create_meeting("new", str(src), "wav")
    items = storage.list_meetings()
    titles = [i["title"] for i in items]
    assert "new" in titles and "old" in titles


def test_save_and_get_meeting(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("t", str(src), "wav")
    storage.save_raw(mid, {"text": "hi", "sentences": [], "spk_count": 0})
    storage.save_processed(mid, "# md")
    storage.save_summary(mid, "## sum")
    storage.update_meta(mid, status="done", spk_count=2)
    data = storage.get_meeting(mid)
    assert data["meta"]["status"] == "done"
    assert data["raw"]["text"] == "hi"
    assert data["processed"] == "# md"
    assert data["summary"] == "## sum"


def test_delete_meeting(data_dir):
    src = data_dir.parent / "a.wav"
    src.write_bytes(b"x")
    mid = storage.create_meeting("t", str(src), "wav")
    storage.delete_meeting(mid)
    assert not (data_dir / mid).exists()
    assert storage.get_meeting(mid) is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_storage.py -v
```

预期：FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `app/storage.py`**

```python
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")


def _slugify(title: str) -> str:
    s = re.sub(r"[^\w一-龥\-]", "-", title.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40] or "untitled"


def create_meeting(title: str, audio_path: str, ext: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    meeting_id = f"{ts}-{_slugify(title)}"
    mdir = DATA_DIR / meeting_id
    mdir.mkdir(parents=True, exist_ok=True)
    dst = mdir / f"audio.{ext}"
    shutil.copy(audio_path, dst)
    meta = {
        "id": meeting_id,
        "title": title,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "audio_file": f"audio.{ext}",
        "audio_wav": None,
        "duration_ms": 0,
        "status": "pending",
        "spk_count": 0,
        "error": None,
    }
    _write_meta(mdir, meta)
    return meeting_id


def _write_meta(mdir: Path, meta: dict) -> None:
    (mdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_meta(mdir: Path) -> dict | None:
    f = mdir / "meta.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def list_meetings() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    items = []
    for d in DATA_DIR.iterdir():
        if not d.is_dir():
            continue
        meta = _read_meta(d)
        if meta:
            items.append(meta)
    items.sort(key=lambda m: m["created_at"], reverse=True)
    return items


def get_meeting(meeting_id: str) -> dict | None:
    mdir = DATA_DIR / meeting_id
    meta = _read_meta(mdir)
    if not meta:
        return None
    raw = _read_json(mdir / "raw.json")
    processed = _read_text(mdir / "processed.md")
    summary = _read_text(mdir / "summary.md")
    return {
        "meta": meta,
        "raw": raw,
        "processed": processed,
        "summary": summary,
    }


def _read_json(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _read_text(p: Path):
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def save_raw(meeting_id: str, raw: dict) -> None:
    (DATA_DIR / meeting_id / "raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_processed(meeting_id: str, md: str) -> None:
    (DATA_DIR / meeting_id / "processed.md").write_text(md, encoding="utf-8")


def save_summary(meeting_id: str, md: str) -> None:
    (DATA_DIR / meeting_id / "summary.md").write_text(md, encoding="utf-8")


def update_meta(meeting_id: str, **fields) -> None:
    mdir = DATA_DIR / meeting_id
    meta = _read_meta(mdir)
    if meta is None:
        return
    meta.update(fields)
    _write_meta(mdir, meta)


def delete_meeting(meeting_id: str) -> None:
    mdir = DATA_DIR / meeting_id
    if mdir.exists():
        shutil.rmtree(mdir)


def meeting_dir(meeting_id: str) -> Path:
    return DATA_DIR / meeting_id
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_storage.py -v
```

预期：4 passed

- [ ] **Step 5: Commit**

```bash
git add app/storage.py test/test_storage.py
git commit -m "feat(storage): file-system CRUD for meetings"
```

---

## Task 5: LLM 抽象 `app/llm.py`

**Files:**
- Create: `app/llm.py`
- Create: `test/test_llm.py`

- [ ] **Step 1: 写失败测试 `test/test_llm.py`**

```python
from unittest import mock

import pytest

from app import llm
from app.config import APIConfig, OllamaConfig, LLMConfig


@pytest.fixture
def cfg_api():
    return LLMConfig(
        mode="api",
        api=APIConfig(base_url="http://x", api_key="k", model="gpt"),
        ollama=OllamaConfig(base_url="", model="", api_key=""),
        polish_chunk_minutes=6,
        temperature=0.3,
        max_retries=2,
    )


def test_chunk_sentences_by_minutes(cfg_api):
    sentences = [
        {"text": "a", "start": 0, "end": 1000, "spk": 0},
        {"text": "b", "start": 1000, "end": 5*60*1000, "spk": 0},
        {"text": "c", "start": 7*60*1000, "end": 13*60*1000, "spk": 1},
    ]
    chunks = llm.chunk_sentences(sentences, minutes=6)
    assert len(chunks) == 2
    assert chunks[0][0]["text"] == "a"
    assert chunks[1][-1]["text"] == "c"


def test_format_chunk(cfg_api):
    chunk = [
        {"text": "hello", "start": 0, "end": 1000, "spk": 0},
        {"text": "world", "start": 1000, "end": 2000, "spk": 1},
    ]
    out = llm.format_chunk(chunk)
    assert "说话人 0" in out
    assert "hello" in out
    assert "说话人 1" in out
    assert "world" in out


def test_polish_calls_chat_per_chunk(cfg_api):
    sentences = [
        {"text": "hi", "start": 0, "end": 1000, "spk": 0},
    ]
    with mock.patch("app.llm._chat", return_value="## 说话人 0\nhi") as m:
        md = llm.polish(sentences, cfg_api)
    assert m.call_count == 1
    assert "## 说话人 0" in md


def test_polish_fallback_on_failure(cfg_api):
    sentences = [
        {"text": "hi", "start": 0, "end": 1000, "spk": 0},
    ]
    with mock.patch("app.llm._chat", side_effect=Exception("boom")):
        md = llm.polish(sentences, cfg_api)
    assert "[整理失败]" in md
    assert "hi" in md


def test_summarize_short(cfg_api):
    with mock.patch("app.llm._chat", return_value="## 核心议题\n...") as m:
        out = llm.summarize("short text", cfg_api)
    assert m.call_count == 1
    assert "核心议题" in out


def test_summarize_long_map_reduce(cfg_api):
    long_md = "x" * 9000
    with mock.patch("app.llm._chat", return_value="partial") as m:
        llm.summarize(long_md, cfg_api)
    # 至少一次 map + 一次 reduce
    assert m.call_count >= 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_llm.py -v
```

预期：FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `app/llm.py`**

```python
import logging
from typing import Callable

from openai import OpenAI

from app.config import LLMConfig

log = logging.getLogger(__name__)

POLISH_PROMPT = """你是一个会议录音整理助手。下面是一段会议的逐句转录（按时间顺序，已标注说话人）。
请整理成规范的会议记录：

规则：
- 保留说话人分段，使用 `## 说话人 N` 作为小标题
- 去除口头禅（那个、然后、嗯、就是、然后然后）和重复词
- 理顺句子结构，使其通顺
- 不要合并不同说话人的内容
- 不要添加未出现的信息
- 同一说话人连续多句可合并为一个或几个完整段落

转录内容：
{input}
"""

SUMMARIZE_PROMPT = """下面是一份整理后的会议记录。请输出会议纪要，格式：

## 核心议题
（列出讨论的主要话题，每条一行）

## 决议
（已确定的事项，每条一行）

## 待办
（用 `- [ ]` 列表，每项后括注负责人）

会议记录：
{input}
"""

REDUCE_PROMPT = """下面是同一会议的多个分段摘要，请合并为一份统一的会议纪要（核心议题 / 决议 / 待办）：

{input}
"""


def _client(cfg: LLMConfig) -> OpenAI:
    if cfg.mode == "api":
        return OpenAI(base_url=cfg.api.base_url, api_key=cfg.api.api_key)
    return OpenAI(base_url=cfg.ollama.base_url, api_key=cfg.ollama.api_key)


def _model_name(cfg: LLMConfig) -> str:
    return cfg.api.model if cfg.mode == "api" else cfg.ollama.model


def _chat(prompt: str, cfg: LLMConfig) -> str:
    client = _client(cfg)
    resp = client.chat.completions.create(
        model=_model_name(cfg),
        messages=[{"role": "user", "content": prompt}],
        temperature=cfg.temperature,
    )
    return resp.choices[0].message.content or ""


def chunk_sentences(sentences: list[dict], minutes: int) -> list[list[dict]]:
    if not sentences:
        return []
    chunk_ms = minutes * 60 * 1000
    chunks = []
    current = [sentences[0]]
    bucket_start = sentences[0]["start"]
    for s in sentences[1:]:
        if s["start"] - bucket_start >= chunk_ms:
            chunks.append(current)
            current = [s]
            bucket_start = s["start"]
        else:
            current.append(s)
    chunks.append(current)
    return chunks


def format_chunk(chunk: list[dict], mark_failed: bool = False) -> str:
    lines = []
    last_spk = None
    tag = " [整理失败]" if mark_failed else ""
    for s in chunk:
        spk = s["spk"]
        if spk != last_spk:
            lines.append(f"\n## 说话人 {spk}{tag}")
            last_spk = spk
        lines.append(s["text"])
    return "\n".join(lines).strip()


def polish(sentences: list[dict], cfg: LLMConfig) -> str:
    chunks = chunk_sentences(sentences, cfg.polish_chunk_minutes)
    outputs = []
    for chunk in chunks:
        prompt = POLISH_PROMPT.format(input=format_chunk(chunk))
        success = False
        for _ in range(cfg.max_retries + 1):
            try:
                outputs.append(_chat(prompt, cfg))
                success = True
                break
            except Exception as e:
                log.warning("polish chunk failed: %s", e)
        if not success:
            outputs.append(format_chunk(chunk, mark_failed=True))
    return "\n\n---\n\n".join(outputs)


def _split_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def summarize(processed_md: str, cfg: LLMConfig) -> str:
    if len(processed_md) < 8000:
        return _chat(SUMMARIZE_PROMPT.format(input=processed_md), cfg)
    chunks = _split_text(processed_md, 6000)
    partials = []
    for c in chunks:
        partials.append(_chat(SUMMARIZE_PROMPT.format(input=c), cfg))
    return _chat(REDUCE_PROMPT.format(input="\n\n".join(partials)), cfg)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_llm.py -v
```

预期：6 passed

- [ ] **Step 5: Commit**

```bash
git add app/llm.py test/test_llm.py
git commit -m "feat(llm): polish + summarize with chunking and map-reduce"
```

---

## Task 6: ASR 封装 `app/asr.py`

**Files:**
- Create: `app/asr.py`
- Create: `test/test_asr.py`

> 说明：FunASR 真实加载需要下载几 GB 模型，单元测试只做"归一化函数"的纯逻辑测试。模型加载/推理留给 `test/smoke_asr.py` 手工验证。

- [ ] **Step 1: 写失败测试 `test/test_asr.py`**

```python
from app import asr


def test_normalize_funasr_output():
    funasr_res = [
        {
            "text": "你好。世界。",
            "timestamp": [[0, 500], [500, 1000]],
            "sentences": [
                {
                    "text": "你好。",
                    "start": 0,
                    "end": 500,
                    "spk": 0,
                    "timestamp": [[0, 500]],
                },
                {
                    "text": "世界。",
                    "start": 500,
                    "end": 1000,
                    "spk": 1,
                    "timestamp": [[500, 1000]],
                },
            ],
        }
    ]
    out = asr.normalize(funasr_res)
    assert out["text"] == "你好。世界。"
    assert len(out["sentences"]) == 2
    assert out["sentences"][0]["spk"] == 0
    assert out["sentences"][1]["end"] == 1000
    assert out["spk_count"] == 2


def test_normalize_missing_sentences_falls_back_to_text():
    funasr_res = [{"text": "x", "timestamp": []}]
    out = asr.normalize(funasr_res)
    assert out["sentences"] == []
    assert out["spk_count"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_asr.py -v
```

预期：FAIL

- [ ] **Step 3: 写 `app/asr.py`**

```python
import logging
import os
from threading import Lock

from app.config import Config, ASRConfig

log = logging.getLogger(__name__)

_model = None
_lock = Lock()


def get_model(cfg: ASRConfig):
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        os.environ["FUNASR_HUB"] = cfg.hub
        os.environ["MODELSCOPE_CACHE"] = cfg.cache_dir
        from funasr import AutoModel
        log.info("loading FunASR models from %s (hub=%s)...", cfg.cache_dir, cfg.hub)
        _model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            vad_revision="v2.0.4",
            punc_model="ct-punc",
            spk_model="cam++",
        )
        log.info("FunASR models loaded")
    return _model


def transcribe(wav_path: str, cfg: ASRConfig) -> dict:
    model = get_model(cfg)
    res = model.generate(
        audio=wav_path,
        batch_size_s=cfg.batch_size_s,
        batch_size_threshold_s=cfg.batch_size_threshold_s,
        sentence_timestamp=True,
        hotword=cfg.hotword or None,
    )
    return normalize(res)


def normalize(funasr_res: list[dict]) -> dict:
    if not funasr_res:
        return {"text": "", "sentences": [], "spk_count": 0}
    first = funasr_res[0]
    sentences = []
    spk_set = set()
    for s in first.get("sentences", []):
        spk = s.get("spk", 0)
        spk_set.add(spk)
        sentences.append({
            "text": s.get("text", ""),
            "start": s.get("start", 0),
            "end": s.get("end", 0),
            "spk": spk,
        })
    return {
        "text": first.get("text", ""),
        "sentences": sentences,
        "spk_count": len(spk_set) if spk_set else 0,
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_asr.py -v
```

预期：2 passed

- [ ] **Step 5: Commit**

```bash
git add app/asr.py test/test_asr.py
git commit -m "feat(asr): funasr AutoModel wrapper with output normalization"
```

---

## Task 7: 后台任务管线 `app/tasks.py`

**Files:**
- Create: `app/tasks.py`
- Create: `test/test_tasks.py`

- [ ] **Step 1: 写失败测试 `test/test_tasks.py`**

```python
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
    # 60 分钟音频 * 0.25 = 900s
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
    # 推进 50%（已耗时 / 预估总耗时）→ progress 应在 5..55 之间
    tasks.advance_asr_progress(state["task_id"], elapsed_s=10)
    p = tasks.get_progress(state["task_id"])["progress"]
    assert 5 <= p < 55
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_tasks.py -v
```

预期：FAIL

- [ ] **Step 3: 写 `app/tasks.py`**

```python
import asyncio
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

from app import asr, audio, llm, storage


_tasks: dict[str, dict] = {}
_lock = asyncio.Lock()

# 进度区间
CONVERT_END = 5
ASR_FAKE_END = 50      # 假进度封顶
ASR_REAL_END = 55
POLISH_START = 55
POLISH_END = 85
SUMMARY_START = 85
SUMMARY_END = 100


def estimate_total_seconds(duration_ms: int) -> float:
    return duration_ms / 1000 * 0.25


def register_task(meeting_id: str) -> dict:
    task_id = uuid.uuid4().hex
    state = {
        "task_id": task_id,
        "meeting_id": meeting_id,
        "status": "pending",
        "progress": 0,
        "step": "",
        "error": None,
        "started_at": 0.0,
        "estimated_total_s": 0.0,
    }
    _tasks[task_id] = state
    return state


def get_progress(task_id: str) -> Optional[dict]:
    state = _tasks.get(task_id)
    return asdict_dataclass_or_dict(state)


def asdict_dataclass_or_dict(state):
    if state is None:
        return None
    return {
        "status": state["status"],
        "progress": state["progress"],
        "step": state["step"],
        "error": state["error"],
    }


def update(task_id: str, **fields) -> None:
    if task_id in _tasks:
        _tasks[task_id].update(fields)


def advance_asr_progress(task_id: str, elapsed_s: float) -> None:
    state = _tasks.get(task_id)
    if not state or state.get("estimated_total_s", 0) <= 0:
        return
    ratio = min(elapsed_s / state["estimated_total_s"], 1.0)
    fake_progress = CONVERT_END + int((ASR_FAKE_END - CONVERT_END) * ratio)
    state["progress"] = max(state["progress"], fake_progress)


async def run_pipeline(meeting_id: str, cfg) -> None:
    async with _lock:
        task_id = None
        for tid, st in _tasks.items():
            if st["meeting_id"] == meeting_id:
                task_id = tid
                break
        if task_id is None:
            state = register_task(meeting_id)
            task_id = state["task_id"]

        try:
            await _convert_audio(task_id, meeting_id, cfg)
            await _run_asr(task_id, meeting_id, cfg)
            await _run_polish(task_id, meeting_id, cfg)
            await _run_summarize(task_id, meeting_id, cfg)
            storage.update_meta(meeting_id, status="done")
            update(task_id, status="done", progress=100, step="完成")
        except Exception as e:
            storage.update_meta(meeting_id, status="error", error=str(e))
            update(task_id, status="error", error=str(e), step="失败")


async def _convert_audio(task_id, meeting_id, cfg) -> None:
    update(task_id, status="converting", progress=0, step="音频转换")
    mdir = storage.meeting_dir(meeting_id)
    meta = storage.get_meeting(meeting_id)["meta"]
    src = mdir / meta["audio_file"]
    dst = mdir / "audio_wav.wav"
    audio.convert_to_wav(str(src), str(dst))
    duration_ms = audio.get_duration_ms(str(dst))
    storage.update_meta(
        meeting_id,
        audio_wav="audio_wav.wav",
        duration_ms=duration_ms,
    )
    update(task_id, progress=CONVERT_END, started_at=time.time(),
           estimated_total_s=estimate_total_seconds(duration_ms))


async def _run_asr(task_id, meeting_id, cfg) -> None:
    update(task_id, status="asr_running", step="语音识别")
    mdir = storage.meeting_dir(meeting_id)
    wav = str(mdir / "audio_wav.wav")
    # 假进度协程（FunASR 同步阻塞，需在另一线程跑推理；进度靠定时器推进）
    loop = asyncio.get_event_loop()
    stop_fake = asyncio.Event()

    async def fake_ticker():
        start = time.time()
        while not stop_fake.is_set():
            await asyncio.sleep(2)
            advance_asr_progress(task_id, time.time() - start)

    ticker = asyncio.create_task(fake_ticker())
    try:
        raw = await loop.run_in_executor(None, asr.transcribe, wav, cfg.asr)
    finally:
        stop_fake.set()
        await ticker
    storage.save_raw(meeting_id, raw)
    storage.update_meta(meeting_id, spk_count=raw.get("spk_count", 0))
    update(task_id, progress=ASR_REAL_END)


async def _run_polish(task_id, meeting_id, cfg) -> None:
    update(task_id, status="llm_polishing", step="LLM 整理")
    data = storage.get_meeting(meeting_id)
    sentences = data["raw"]["sentences"]
    chunks_n = max(1, (len(sentences) // 30) + 1)
    loop = asyncio.get_event_loop()
    # 简单按 chunk 数推进（实际 polish 内部分段，这里只估算）
    md = await loop.run_in_executor(None, llm.polish, sentences, cfg.llm)
    storage.save_processed(meeting_id, md)
    update(task_id, progress=POLISH_END)


async def _run_summarize(task_id, meeting_id, cfg) -> None:
    update(task_id, status="llm_summarizing", step="LLM 总结")
    data = storage.get_meeting(meeting_id)
    processed = data["processed"] or ""
    loop = asyncio.get_event_loop()
    md = await loop.run_in_executor(None, llm.summarize, processed, cfg.llm)
    storage.save_summary(meeting_id, md)
    update(task_id, progress=SUMMARY_END)


async def retry_llm(meeting_id: str, cfg) -> str:
    """复用 raw.json，只重跑 polish + summarize"""
    state = register_task(meeting_id)
    task_id = state["task_id"]
    async with _lock:
        try:
            await _run_polish(task_id, meeting_id, cfg)
            await _run_summarize(task_id, meeting_id, cfg)
            storage.update_meta(meeting_id, status="done", error=None)
            update(task_id, status="done", progress=100, step="完成")
        except Exception as e:
            storage.update_meta(meeting_id, status="error", error=str(e))
            update(task_id, status="error", error=str(e))
    return task_id
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_tasks.py -v
```

预期：4 passed

- [ ] **Step 5: Commit**

```bash
git add app/tasks.py test/test_tasks.py
git commit -m "feat(tasks): async pipeline with progress estimation"
```

---

## Task 8: FastAPI 应用 `app/main.py`

**Files:**
- Create: `app/main.py`
- Create: `test/test_main.py`

- [ ] **Step 1: 写失败测试 `test/test_main.py`**

```python
import io
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import main, storage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 跳过真实 pipeline，直接造状态
    async def fake_run(meeting_id, cfg):
        storage.update_meta(meeting_id, status="done")
    monkeypatch.setattr(main.tasks, "run_pipeline", fake_run)
    with TestClient(main.app) as c:
        yield c


def test_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_upload_and_list(client):
    audio_bytes = b"fake-audio"
    files = {"audio": ("m.m4a", io.BytesIO(audio_bytes), "audio/m4a")}
    data = {"title": "Demo Meeting"}
    r = client.post("/api/upload", files=files, data=data)
    assert r.status_code == 200
    body = r.json()
    assert "meeting_id" in body and "task_id" in body
    meetings = client.get("/api/meetings").json()
    assert any(m["id"] == body["meeting_id"] for m in meetings)


def test_upload_rejects_non_audio(client):
    files = {"audio": ("t.txt", io.BytesIO(b"x"), "text/plain")}
    data = {"title": "x"}
    r = client.post("/api/upload", files=files, data=data)
    assert r.status_code == 415


def test_get_meeting(client):
    files = {"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}
    r = client.post("/api/upload", files=files, data={"title": "T"})
    mid = r.json()["meeting_id"]
    detail = client.get(f"/api/meetings/{mid}").json()
    assert detail["meta"]["id"] == mid


def test_delete_meeting(client):
    files = {"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")}
    mid = client.post("/api/upload", files=files, data={"title": "T"}).json()["meeting_id"]
    r = client.delete(f"/api/meetings/{mid}")
    assert r.status_code == 200
    assert client.get(f"/api/meetings/{mid}").status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest test/test_main.py -v
```

预期：FAIL

- [ ] **Step 3: 写 `app/main.py`**

```python
import asyncio
import logging
from pathlib import Path

from fastapi import (
    BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import asr, audio, storage, tasks
from app.config import Config, load_config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

CONFIG_PATH = Path("config.yaml")
config: Config = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else None

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="FunASR Meeting Transcription")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ALLOWED_AUDIO_EXTS = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "webm"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/m/{meeting_id}", response_class=HTMLResponse)
async def meeting_page(meeting_id: str):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    return (STATIC_DIR / "meeting.html").read_text(encoding="utf-8")


@app.post("/api/upload")
async def upload(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    title: str = Form(...),
):
    ext = (audio.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(415, detail=f"unsupported format: {ext}")
    uploads_dir = storage.DATA_DIR / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = uploads_dir / f"upload_{asyncio.get_event_loop().time()}.{ext}"
    tmp_path.write_bytes(await audio.read())
    meeting_id = storage.create_meeting(title=title, audio_path=str(tmp_path), ext=ext)
    tmp_path.unlink(missing_ok=True)
    state = tasks.register_task(meeting_id)
    background_tasks.add_task(tasks.run_pipeline, meeting_id, config)
    return {"task_id": state["task_id"], "meeting_id": meeting_id}


@app.get("/api/tasks/{task_id}")
async def task_status(task_id: str):
    state = tasks.get_progress(task_id)
    if state is None:
        raise HTTPException(404)
    return state


@app.get("/api/meetings")
async def list_meetings():
    return storage.list_meetings()


@app.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: str):
    data = storage.get_meeting(meeting_id)
    if data is None:
        raise HTTPException(404)
    return data


@app.get("/api/meetings/{meeting_id}/audio")
async def get_audio(meeting_id: str):
    data = storage.get_meeting(meeting_id)
    if data is None:
        raise HTTPException(404)
    audio_path = storage.meeting_dir(meeting_id) / data["meta"]["audio_file"]
    if not audio_path.exists():
        raise HTTPException(404)
    return FileResponse(audio_path)


@app.get("/api/meetings/{meeting_id}/export")
async def export(meeting_id: str, format: str = "md"):
    data = storage.get_meeting(meeting_id)
    if data is None:
        raise HTTPException(404)
    mdir = storage.meeting_dir(meeting_id)
    if format == "md":
        path = mdir / "processed.md"
        media_type = "text/markdown"
    elif format == "txt":
        text = _to_plain_text(data["raw"])
        path = mdir / "export.txt"
        path.write_text(text, encoding="utf-8")
        media_type = "text/plain"
    elif format == "srt":
        text = _to_srt(data["raw"])
        path = mdir / "export.srt"
        path.write_text(text, encoding="utf-8")
        media_type = "application/x-subrip"
    else:
        raise HTTPException(400, "format must be md/txt/srt")
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post("/api/meetings/{meeting_id}/retry-llm")
async def retry_llm(meeting_id: str, background_tasks: BackgroundTasks):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    task_id = await tasks.retry_llm(meeting_id, config)
    return {"task_id": task_id}


@app.delete("/api/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str):
    if storage.get_meeting(meeting_id) is None:
        raise HTTPException(404)
    storage.delete_meeting(meeting_id)
    return {"ok": True}


def _fmt_ts(ms: int) -> str:
    s = ms / 1000
    h, rem = divmod(int(s), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _to_plain_text(raw: dict) -> str:
    if not raw:
        return ""
    lines = []
    for s in raw.get("sentences", []):
        lines.append(f"[{_fmt_ts(s['start'])}] 说话人{s['spk']}  {s['text']}")
    return "\n".join(lines)


def _to_srt(raw: dict) -> str:
    if not raw:
        return ""
    lines = []
    for i, s in enumerate(raw.get("sentences", []), 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(s['start'])} --> {_srt_ts(s['end'])}")
        lines.append(f"[说话人{s['spk']}] {s['text']}")
        lines.append("")
    return "\n".join(lines)


def _srt_ts(ms: int) -> str:
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test/test_main.py -v
```

预期：5 passed

- [ ] **Step 5: Commit**

```bash
git add app/main.py test/test_main.py
git commit -m "feat(api): FastAPI routes for upload/tasks/meetings/export"
```

---

## Task 9: 前端首页 `static/index.html` + `app.js` + `style.css`

**Files:**
- Create: `static/index.html`
- Create: `static/style.css`
- Create: `static/app.js`

> 此任务无单元测试，验收靠手工（见 Task 13 验收清单）。

- [ ] **Step 1: 写 `static/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>FunASR 会议转录</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>FunASR 会议转录</h1>
  </header>
  <main class="container">
    <section class="upload-card">
      <div id="dropzone" class="dropzone">
        <p>📁 拖拽音频文件到此，或点击选择</p>
        <p class="hint">支持 wav / mp3 / m4a / aac / flac / ogg / opus</p>
        <input id="file-input" type="file" accept="audio/*,.m4a,.aac,.opus" hidden>
      </div>
      <div class="form-row">
        <label>会议标题 <input id="title" type="text" placeholder="例如：产品周会"></label>
        <button id="submit-btn" disabled>开始转录</button>
      </div>
      <div id="progress" class="progress hidden">
        <div class="bar"><div id="bar-fill" class="bar-fill"></div></div>
        <div id="progress-text" class="progress-text"></div>
      </div>
      <div id="error" class="error hidden"></div>
    </section>

    <section>
      <h2>历史会议</h2>
      <ul id="history" class="history-list"></ul>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 `static/style.css`**

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica", sans-serif;
  color: #222;
  background: #f6f7f9;
}
header {
  background: #2b3a55;
  color: #fff;
  padding: 16px 32px;
}
header h1 { margin: 0; font-size: 18px; }
.container {
  max-width: 880px;
  margin: 24px auto;
  padding: 0 16px;
}
.upload-card, .history-list {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.dropzone {
  border: 2px dashed #c2cad6;
  border-radius: 6px;
  padding: 32px;
  text-align: center;
  cursor: pointer;
  color: #6b7280;
}
.dropzone.dragover { border-color: #2b6cb0; background: #ebf4ff; }
.dropzone .hint { font-size: 12px; color: #9ca3af; }
.form-row {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 16px;
}
.form-row label { flex: 1; }
input[type=text] {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 14px;
}
button {
  background: #2b6cb0;
  color: #fff;
  border: none;
  padding: 9px 18px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}
button:disabled { background: #9ca3af; cursor: not-allowed; }
.progress { margin-top: 16px; }
.progress .bar {
  background: #e5e7eb;
  border-radius: 4px;
  height: 8px;
  overflow: hidden;
}
.bar-fill {
  background: #2b6cb0;
  height: 100%;
  width: 0%;
  transition: width 0.4s;
}
.progress-text { font-size: 13px; color: #4b5563; margin-top: 6px; }
.error {
  margin-top: 12px;
  padding: 10px 12px;
  background: #fee2e2;
  color: #991b1b;
  border-radius: 4px;
  font-size: 13px;
}
.hidden { display: none; }
.history-list {
  list-style: none;
  padding: 8px;
  margin-top: 16px;
}
.history-list li {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.history-list li:last-child { border-bottom: none; }
.history-list a {
  color: #2b6cb0;
  text-decoration: none;
  font-weight: 500;
}
.history-list .meta { font-size: 12px; color: #6b7280; }
.status-error { color: #b91c1c; }
.status-pending, .status-asr_running, .status-llm_polishing, .status-llm_summarizing {
  color: #b45309;
}
.status-done { color: #15803d; }
```

- [ ] **Step 3: 写 `static/app.js`**

```javascript
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const titleInput = document.getElementById('title');
const submitBtn = document.getElementById('submit-btn');
const progressEl = document.getElementById('progress');
const barFill = document.getElementById('bar-fill');
const progressText = document.getElementById('progress-text');
const errorEl = document.getElementById('error');
const historyList = document.getElementById('history');

let selectedFile = null;

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files.length) setFile(fileInput.files[0]); });

function setFile(f) {
  selectedFile = f;
  dropzone.querySelector('p').textContent = `📎 ${f.name} (${(f.size/1024/1024).toFixed(1)} MB)`;
  submitBtn.disabled = !titleInput.value.trim();
}

titleInput.addEventListener('input', () => {
  submitBtn.disabled = !(selectedFile && titleInput.value.trim());
});

submitBtn.addEventListener('click', startUpload);

async function startUpload() {
  errorEl.classList.add('hidden');
  submitBtn.disabled = true;
  progressEl.classList.remove('hidden');
  setProgress(0, '上传中...');

  const fd = new FormData();
  fd.append('audio', selectedFile);
  fd.append('title', titleInput.value.trim());

  try {
    const r = await fetch('/api/upload', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || '上传失败');
    }
    const { task_id, meeting_id } = await r.json();
    pollTask(task_id, meeting_id);
  } catch (e) {
    showError(e.message);
    progressEl.classList.add('hidden');
    submitBtn.disabled = false;
  }
}

function pollTask(taskId, meetingId) {
  const timer = setInterval(async () => {
    try {
      const r = await fetch(`/api/tasks/${taskId}`);
      const s = await r.json();
      setProgress(s.progress, s.step);
      if (s.status === 'done') {
        clearInterval(timer);
        location.href = `/m/${meetingId}`;
      } else if (s.status === 'error') {
        clearInterval(timer);
        showError(s.error || '处理失败');
        submitBtn.disabled = false;
      }
    } catch (e) {
      clearInterval(timer);
      showError(e.message);
    }
  }, 2000);
}

function setProgress(pct, step) {
  barFill.style.width = `${pct}%`;
  progressText.textContent = `${pct}% · ${step || ''}`;
}

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove('hidden');
}

async function loadHistory() {
  const r = await fetch('/api/meetings');
  const items = await r.json();
  historyList.innerHTML = '';
  if (!items.length) {
    historyList.innerHTML = '<li class="meta">暂无</li>';
    return;
  }
  for (const m of items) {
    const li = document.createElement('li');
    li.innerHTML = `
      <div>
        <a href="/m/${m.id}">${escapeHtml(m.title)}</a>
        <div class="meta">${m.created_at} · ${fmtDuration(m.duration_ms)} · ${m.spk_count} 人</div>
      </div>
      <div class="status-${m.status}">${statusLabel(m.status)}</div>
    `;
    historyList.appendChild(li);
  }
}

function fmtDuration(ms) {
  if (!ms) return '--';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2,'0')}`;
}

function statusLabel(s) {
  return {
    pending: '排队',
    converting: '转换中',
    asr_running: '识别中',
    llm_polishing: '整理中',
    llm_summarizing: '总结中',
    done: '完成',
    error: '失败',
  }[s] || s;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

loadHistory();
```

- [ ] **Step 4: 手工启动验证**

```bash
cp config.yaml.example config.yaml
./run.sh  # 如果 run.sh 还没写，先跳过；直接 uvicorn app.main:app --port 8000
```

浏览器打开 `http://127.0.0.1:8000`：
- 上传区域可拖拽
- 历史会议列表显示"暂无"或已有记录

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat(ui): index page with upload and history list"
```

---

## Task 10: 详情页 `static/meeting.html`

**Files:**
- Create: `static/meeting.html`

> `app.js` 中既有首页逻辑，详情页用单独 inline `<script>` 或追加到 `app.js` 末尾。这里用 inline 保持简单。

- [ ] **Step 1: 写 `static/meeting.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>会议详情 · FunASR</title>
  <link rel="stylesheet" href="/static/style.css">
  <style>
    .tabs { display: flex; gap: 4px; border-bottom: 1px solid #e5e7eb; margin-bottom: 16px; }
    .tabs button {
      background: transparent;
      color: #374151;
      border: none;
      padding: 10px 16px;
      border-bottom: 2px solid transparent;
      border-radius: 0;
      font-size: 14px;
    }
    .tabs button.active { color: #2b6cb0; border-bottom-color: #2b6cb0; }
    .panel { display: none; }
    .panel.active { display: block; }
    .transcript-line {
      padding: 8px 12px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      font-size: 14px;
    }
    .transcript-line:hover { background: #f9fafb; }
    .transcript-line .ts { color: #6b7280; font-family: monospace; margin-right: 10px; }
    .transcript-line .spk { color: #2b6cb0; font-weight: 500; margin-right: 10px; }
    .compare-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .compare-col {
      background: #fff;
      padding: 16px;
      border-radius: 6px;
      max-height: 70vh;
      overflow-y: auto;
      font-size: 14px;
      line-height: 1.7;
    }
    .compare-col h3 { margin-top: 0; font-size: 13px; color: #6b7280; }
    .rendered-md { background: #fff; padding: 20px; border-radius: 6px; line-height: 1.8; }
    .rendered-md h2 { margin-top: 24px; color: #1f2937; }
    .rendered-md h2:first-child { margin-top: 0; }
    .audio-bar {
      position: sticky;
      bottom: 0;
      background: #fff;
      padding: 10px 16px;
      border-top: 1px solid #e5e7eb;
      display: flex;
      gap: 12px;
      align-items: center;
    }
    .retry-btn { background: #b91c1c; }
    .export-row { display: flex; gap: 8px; align-items: center; margin-left: auto; }
    .export-row select { padding: 6px; border: 1px solid #d1d5db; border-radius: 4px; }
  </style>
</head>
<body>
  <header>
    <h1><a href="/" style="color:#fff;text-decoration:none;">◄</a> <span id="m-title">会议</span></h1>
  </header>
  <main class="container">
    <div class="meta-row" id="meta-row" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;font-size:13px;color:#6b7280;">
      <span id="m-meta"></span>
      <div class="export-row">
        <select id="export-format">
          <option value="md">整理版 .md</option>
          <option value="txt">原文 .txt</option>
          <option value="srt">字幕 .srt</option>
        </select>
        <button id="export-btn">导出</button>
        <button id="retry-btn" class="retry-btn hidden">重试 LLM</button>
      </div>
    </div>

    <div class="tabs">
      <button class="tab-btn active" data-tab="raw">原文</button>
      <button class="tab-btn" data-tab="processed">整理版</button>
      <button class="tab-btn" data-tab="summary">会议总结</button>
      <button class="tab-btn" data-tab="compare">原文↔整理对照</button>
    </div>

    <div id="tab-raw" class="panel active">
      <div id="transcript"></div>
    </div>

    <div id="tab-processed" class="panel">
      <div id="processed-md" class="rendered-md"></div>
    </div>

    <div id="tab-summary" class="panel">
      <div id="summary-md" class="rendered-md"></div>
    </div>

    <div id="tab-compare" class="panel">
      <div class="compare-grid">
        <div class="compare-col" id="compare-raw">
          <h3>原文（按时间戳）</h3>
          <div id="compare-raw-body"></div>
        </div>
        <div class="compare-col" id="compare-processed">
          <h3>整理版</h3>
          <div id="compare-processed-body"></div>
        </div>
      </div>
    </div>
  </main>

  <div class="audio-bar">
    <audio id="audio-player" controls style="width:100%;"></audio>
  </div>

  <script>
    const pathParts = location.pathname.split('/');
    const meetingId = pathParts[pathParts.length - 1];

    function fmtTs(ms) {
      const s = Math.floor(ms / 1000);
      const m = Math.floor(s / 60);
      const sec = s % 60;
      return `${m}:${String(sec).padStart(2,'0')}`;
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    function renderMd(md) {
      if (!md) return '<p style="color:#9ca3af;">（空）</p>';
      // 极简 markdown：## 标题、段落、- [ ] 待办
      const lines = escapeHtml(md).split('\n');
      let html = '';
      let inList = false;
      for (let line of lines) {
        if (line.startsWith('## ')) {
          if (inList) { html += '</ul>'; inList = false; }
          html += `<h2>${line.slice(3)}</h2>`;
        } else if (line.match(/^- \[/)) {
          if (!inList) { html += '<ul>'; inList = true; }
          html += `<li>${line.replace(/^- \[ \] /, '☐ ').replace(/^- \[x\] /i, '☑ ')}</li>`;
        } else if (line.trim() === '') {
          if (inList) { html += '</ul>'; inList = false; }
        } else {
          if (inList) { html += '</ul>'; inList = false; }
          html += `<p>${line}</p>`;
        }
      }
      if (inList) html += '</ul>';
      return html;
    }

    let audioPlayer = document.getElementById('audio-player');
    audioPlayer.src = `/api/meetings/${meetingId}/audio`;

    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
      });
    });

    document.getElementById('export-btn').addEventListener('click', () => {
      const fmt = document.getElementById('export-format').value;
      location.href = `/api/meetings/${meetingId}/export?format=${fmt}`;
    });

    document.getElementById('retry-btn').addEventListener('click', async () => {
      if (!confirm('重新调用 LLM 整理 + 总结？')) return;
      const r = await fetch(`/api/meetings/${meetingId}/retry-llm`, { method: 'POST' });
      const { task_id } = await r.json();
      alert('已提交，稍后刷新页面查看');
      location.reload();
    });

    function renderRaw(container, sentences, clickable) {
      container.innerHTML = '';
      for (const s of sentences) {
        const div = document.createElement('div');
        div.className = 'transcript-line';
        div.innerHTML = `<span class="ts">[${fmtTs(s.start)}]</span><span class="spk">说话人${s.spk}</span><span>${escapeHtml(s.text)}</span>`;
        if (clickable) {
          div.addEventListener('click', () => {
            audioPlayer.currentTime = s.start / 1000;
            audioPlayer.play();
          });
        }
        container.appendChild(div);
      }
    }

    // 双栏滚动联动
    function bindScrollSync() {
      const a = document.getElementById('compare-raw');
      const b = document.getElementById('compare-processed');
      let syncing = false;
      a.addEventListener('scroll', () => {
        if (syncing) return;
        syncing = true;
        b.scrollTop = a.scrollTop;
        setTimeout(() => syncing = false, 50);
      });
      b.addEventListener('scroll', () => {
        if (syncing) return;
        syncing = true;
        a.scrollTop = b.scrollTop;
        setTimeout(() => syncing = false, 50);
      });
    }

    async function load() {
      const r = await fetch(`/api/meetings/${meetingId}`);
      if (!r.ok) { alert('会议不存在'); location.href = '/'; return; }
      const data = await r.json();
      const meta = data.meta;
      document.getElementById('m-title').textContent = meta.title;
      const durationStr = meta.duration_ms ? `${Math.floor(meta.duration_ms/60000)}分${Math.floor((meta.duration_ms%60000)/1000)}秒` : '--';
      document.getElementById('m-meta').textContent =
        `${meta.created_at} · ${durationStr} · ${meta.spk_count} 人 · ${statusLabel(meta.status)}`;
      if (meta.status === 'error') {
        document.getElementById('retry-btn').classList.remove('hidden');
      }
      const sentences = (data.raw && data.raw.sentences) || [];
      renderRaw(document.getElementById('transcript'), sentences, true);
      renderRaw(document.getElementById('compare-raw-body'), sentences, false);
      document.getElementById('processed-md').innerHTML = renderMd(data.processed);
      document.getElementById('summary-md').innerHTML = renderMd(data.summary);
      document.getElementById('compare-processed-body').innerHTML = renderMd(data.processed);
      bindScrollSync();
    }

    function statusLabel(s) {
      return {done:'完成', error:'失败', pending:'处理中'}[s] || s;
    }

    load();
  </script>
</body>
</html>
```

- [ ] **Step 2: 手工启动验证**

```bash
uvicorn app.main:app --port 8000
```

访问首页 → 上传一段音频 → 跳转到 `/m/{id}` → 4 个 Tab 切换、音频播放、对照视图联动、导出下拉。

- [ ] **Step 3: Commit**

```bash
git add static/meeting.html
git commit -m "feat(ui): meeting detail page with 4 tabs and audio player"
```

---

## Task 11: 启动脚本与 README

**Files:**
- Create: `run.sh`
- Create: `README.md`
- Create: `.env.example`

- [ ] **Step 1: 写 `run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "需要先安装 ffmpeg: brew install ffmpeg"
  exit 1
fi

if [ ! -d .venv ]; then
  uv venv --python 3.11
fi
source .venv/bin/activate
uv pip install -e .

if [ ! -f config.yaml ]; then
  echo "提示：复制 config.yaml.example 为 config.yaml 并按需修改"
  cp config.yaml.example config.yaml
fi

HOST=$(grep -E '^\s*host:' config.yaml | awk '{print $2}' | tr -d '"')
PORT=$(grep -E '^\s*port:' config.yaml | awk '{print $2}' | tr -d '"')
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8000}

if grep -q 'mode: api' config.yaml && [ -z "${LLM_API_KEY:-}" ]; then
  echo "警告：LLM_API_KEY 未设置，LLM 功能将不可用"
fi

echo "启动: http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
```

```bash
chmod +x run.sh
```

- [ ] **Step 2: 写 `.env.example`**

```
LLM_API_KEY=your-zhipu-or-other-api-key
```

- [ ] **Step 3: 写 `README.md`**

````markdown
# FunASR 本地会议转录系统

基于 [FunASR](https://github.com/modelscope/FunASR) 的多人会议录音转文字系统。

## 特性

- 说话人自动区分（基于 CAM++）
- 逐句时间戳
- LLM 整理口语化文字 + 生成会议纪要
- 支持 GLM / DeepSeek / 通义 / Kimi / OpenAI 等 OpenAI 兼容 API，也支持本地 Ollama
- Web 界面拖拽上传、历史回看
- 支持 wav / mp3 / m4a / aac / flac / ogg / opus

## 环境要求

- macOS / Linux
- Python 3.11
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
| `llm.api.*` | OpenAI 兼容 API 配置 |
| `llm.ollama.*` | 本地 Ollama 配置 |
| `llm.polish_chunk_minutes` | 整理时分段时长（分钟） |

## 使用 Ollama 本地模型

```bash
# 安装并启动 ollama
ollama pull qwen2.5:7b
ollama serve

# 修改 config.yaml: llm.mode: ollama
./run.sh
```

## 已知限制

- 说话人分离基于音色聚类，可能因设备/位置变化拆分或合并 ID
- LLM 整理可能轻微改变原意，对照视图可用于核对
- 无用户认证，仅适合本地运行
- 进行中的任务状态保存在内存，重启服务会丢失

## 验收清单

1. 上传 10 分钟真实会议音频，等待 pipeline 完成
2. 原文：说话人区分正确、时间戳对齐音频
3. 整理版：口语化减少、保留说话人分段
4. 总结：议题/决议/待办齐全
5. 对照视图：左右滚动同步
6. 历史列表：刷新首页可回看
7. 删除：目录与列表同步清除
8. 长音频：上传 60-90 分钟音频，观察内存与进度推进
9. 格式：分别上传 m4a、mp3、flac 均能处理

## License

MIT
````

- [ ] **Step 4: Commit**

```bash
git add run.sh .env.example README.md
git commit -m "docs: add run script, env example, and README"
```

---

## Task 12: 冒烟脚本

**Files:**
- Create: `test/smoke_asr.py`
- Create: `test/smoke_llm.py`
- Create: `test/README.md`

- [ ] **Step 1: 写 `test/smoke_asr.py`**

```python
"""手工冒烟：跑真实音频，验证 ASR 输出。

用法：
    uv run python test/smoke_asr.py /path/to/audio.m4a
"""
import json
import sys
from pathlib import Path

from app.asr import transcribe
from app.config import load_config


def main():
    if len(sys.argv) < 2:
        print("usage: python test/smoke_asr.py <audio_path>")
        sys.exit(1)
    audio_path = sys.argv[1]
    cfg = load_config("config.yaml")
    print(f"loading models and transcribing {audio_path}...")
    result = transcribe(audio_path, cfg.asr)
    print(f"spk_count: {result['spk_count']}")
    print(f"sentences: {len(result['sentences'])}")
    print(f"first 3: {json.dumps(result['sentences'][:3], ensure_ascii=False, indent=2)}")
    out = Path("data") / "smoke_raw.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 写 `test/smoke_llm.py`**

```python
"""手工冒烟：读取 raw.json，跑 polish + summarize，打印结果。

用法：
    LLM_API_KEY=xxx uv run python test/smoke_llm.py data/smoke_raw.json
"""
import json
import sys
from pathlib import Path

from app.config import load_config
from app.llm import polish, summarize


def main():
    if len(sys.argv) < 2:
        print("usage: python test/smoke_llm.py <raw.json>")
        sys.exit(1)
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = load_config("config.yaml")
    print("polishing...")
    processed = polish(raw["sentences"], cfg.llm)
    Path("data/smoke_processed.md").write_text(processed, encoding="utf-8")
    print(f"  -> {len(processed)} chars, saved data/smoke_processed.md")
    print("summarizing...")
    summary = summarize(processed, cfg.llm)
    Path("data/smoke_summary.md").write_text(summary, encoding="utf-8")
    print(f"  -> {len(summary)} chars, saved data/smoke_summary.md")
    print("\n=== summary ===")
    print(summary)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 写 `test/README.md`**

```markdown
# 测试

## 单元测试

```bash
uv pip install -e ".[dev]"
pytest -v
```

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

验证：`data/smoke_processed.md` 含 `## 说话人 N` 分段；`data/smoke_summary.md` 含 `## 核心议题 / ## 决议 / ## 待办`。

## 测试音频

由于版权，不放仓库。可用：
- 自己录一段 1-2 分钟多人对话
- 或下载公开会议录音（如播客片段）
```

- [ ] **Step 4: 运行全部单元测试**

```bash
pytest -v
```

预期：所有 `test_*.py` 通过（21 个测试左右）。

- [ ] **Step 5: Commit**

```bash
git add test/smoke_asr.py test/smoke_llm.py test/README.md
git commit -m "test: add smoke scripts for ASR and LLM"
```

---

## Task 13: 端到端手工验收

**Files:** 无代码变更，仅运行验证。

- [ ] **Step 1: 启动服务**

```bash
export LLM_API_KEY=your-zhipu-key   # 或切到 ollama 模式
./run.sh
```

- [ ] **Step 2: 浏览器验收清单（对照 README §验收清单）**

1. 浏览器打开 `http://127.0.0.1:8000`
2. 上传一段 10 分钟真实会议音频（如无，可用手机录一段 2-3 分钟多人对话作为最小验证）
3. 进度条推进：转换 → 识别 → 整理 → 总结
4. 详情页 4 个 Tab：
   - 原文：说话人 ID 与时间戳合理
   - 整理版：`## 说话人 N` 分段清晰
   - 总结：议题/决议/待办齐全
   - 对照：左右滚动同步
5. 点击原文行跳转音频播放
6. 导出下拉：选 md/txt/srt 各下载一次，内容符合预期
7. 首页历史列表出现本次会议
8. 删除会议：列表和目录同步消失
9. （可选）上传 60 分钟音频，观察内存占用 < 12GB

- [ ] **Step 3: 长音频回归（至少做一次）**

准备一段 60 分钟以上音频，重复 Step 2 的 2-4。重点检查：
- ASR 不 OOM
- LLM 分段 polish 正常完成
- 总耗时在 15-30 分钟内（M4 CPU）

- [ ] **Step 4: 提交最终状态**

```bash
git status   # 应无未跟踪文件
git log --oneline | head -15   # 确认提交历史
```

---

## 完成标志

全部任务通过后：
- 所有单元测试 PASS
- README 验收清单完成
- 长音频（≥60min）至少跑过一次
- 多格式（m4a/mp3/flac）至少各跑过一次
