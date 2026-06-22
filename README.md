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
- Git LFS（macOS：`brew install git-lfs`）—— 用于预下载模型
- 首次启动会下载约 3-4GB FunASR 模型

## 快速开始

```bash
git clone <repo> funasr
cd funasr
cp config.yaml.example config.yaml
cp .env.example .env  # 编辑 .env，填入 LLM_API_KEY（api 模式）

bash scripts/download_models.sh   # 预下载模型（推荐，见下文）
./run.sh
```

## 预下载模型（推荐）

FunASR 需要 4 个模型（ASR / VAD / 标点 / 说话人），共约 3-4GB。首次运行时
FunASR SDK 会从 modelscope 自动下载，但 macOS 上 uv 装的 Python 是临时签名，
偶发会出现网络访问限制。推荐**在启动服务之前**用 `git clone` 预下载——`git`
是 Apple 签名，走系统网络路径，更稳。

### 方法 A：用脚本自动下载

```bash
bash scripts/download_models.sh
```

默认下载到 `./models/`，下载完后 `app/asr.py` 启动时会自动识别本地目录并跳过
SDK 下载。

也可以指定其他路径：

```bash
bash scripts/download_models.sh /path/to/models
# 然后在 config.yaml 改 asr.cache_dir: /path/to/models
```

### 方法 B：手动 git clone

```bash
mkdir -p models && cd models
git lfs install

git clone --depth 1 https://www.modelscope.cn/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch.git paraformer-zh
git clone --depth 1 https://www.modelscope.cn/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch.git fsmn-vad
git clone --depth 1 https://www.modelscope.cn/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch.git ct-punc
git clone --depth 1 https://www.modelscope.cn/iic/speech_campplus_sv_zh-cn_16k-common.git campp
```

目录名要严格对应（`paraformer-zh` / `fsmn-vad` / `ct-punc` / `campp`），否则
`app/asr.py` 无法识别。

### 方法 C：用 modelscope SDK 下载

如果你环境正常，直接启动服务就行：

```bash
./run.sh
```

第一次推理时 FunASR 会自己从 modelscope 下载到 `asr.cache_dir`（默认 `./models/`）。
下载过程没有进度回调，60 分钟音频的首次任务可能卡在 "语音识别" 阶段 10-20 分钟，
属于正常现象。

### 模型下载失败的网络排查

```bash
# 1. 测试直连
curl -sS -o /dev/null -w "%{http_code}\n" https://www.modelscope.cn/

# 2. 如果 curl 通但 Python 不通（macOS mDNSResponder 偶发问题）
cp dns_hosts.txt.example dns_hosts.txt
# 编辑 dns_hosts.txt，填入 curl 测试可用的 IP（用 dig / nslookup 查）
# 启动服务时会自动加载

# 3. 如果用代理
export HTTPS_PROXY=http://your-proxy:port
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

## 故障排查

### 首次启动卡在"语音识别"或下载超时

FunASR 从 modelscope.cn 下载模型。如果系统 DNS 或网络问题导致解析失败：

```bash
# 1. 测试直连
curl -sS -o /dev/null -w "%{http_code}\n" https://www.modelscope.cn/

# 2. 如果 curl 通但 Python 不通（macOS mDNSResponder 偶发问题）
#    用 dns_hosts.txt 绕过系统 DNS：
cp dns_hosts.txt.example dns_hosts.txt
# 编辑 dns_hosts.txt，填入 curl 测试可用的 IP（用 dig / nslookup 查）
# 启动服务时会自动加载

# 3. 如果用代理
export HTTPS_PROXY=http://your-proxy:port
./run.sh
```

### LLM 调用失败

- API 模式：检查 `LLM_API_KEY` 环境变量是否设置、`base_url` 是否正确
- Ollama 模式：检查 `ollama serve` 是否启动、模型名是否在 `ollama list` 中
- 整理失败的句子会标记 `[整理失败]`，可在详情页点"重试 LLM"

### 推理模型（Qwen3、DeepSeek-R1）输出含思考过程

代码已自动剥离 `<think>...</think>` 块。如果换用其他会输出推理过程的模型，请保留此清理逻辑。

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
