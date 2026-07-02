[English](README.en.md) | 中文

# 听记

> 本地会议录音转写与纪要——把录音丢进去，自动得到原文、整理稿和会议纪要。数据全程留在你自己的电脑上。

![首页](docs/screenshot-home.png)

基于 [FunASR](https://github.com/modelscope/FunASR)（语音识别 + 说话人分离 + 标点恢复）与大语言模型整理。适合**会议、访谈、讲座**等长音频；跨平台（macOS / Windows WSL2 + GPU），识别无需联网。

## 特性

- **说话人自动区分**：基于 CAM++ 音色聚类，自动分清"谁在说话"，可改成真实名字并同步到所有视图与导出
- **发言人时间轴**：顶部一条按累计发言时长的比例色条，一眼看出谁说得多；点击定位该说话人第一句，播放时高亮当前说话人
- **逐句时间戳**：点任意句定位音频（不强制播放），播放时当前句自动高亮 + 滚动跟随
- **原文↔整理对照**：左右双栏按时间戳精确关联，hover 高亮、点击跳转音频、播放同步
- **手动校对 + 热词**：双击句子纠正识别错误，可一键加入热词，提升后续准确率
- **一键整理**：把口语化的原文整理成通顺文字，再生成结构化会议纪要（概述 / 决议 / 待办 / 待讨论）；整理前可选总结模板、填会议背景与常用术语
- **总结模板**：内置普通会议 / 周会 / 访谈采访 / 项目管理，也可自定义（背景、常用词语、总结方向 / 内容 / 框架），不同会议侧重不同
- **实时日志**：进度条 + ASR 设备（GPU 型号）/ 模型 / 分段耗时；超过 15 秒无更新会警告，一眼看出是否卡住
- **LLM 自由选**：本地 Ollama，或任何 OpenAI 兼容 API（GLM / DeepSeek / 通义 / Kimi / OpenAI …）
- **全 Web 配置**：数据目录、LLM、热词、总结模板都在网页里配，不用改文件
- **导出** `.md` / `.txt` / `.srt`（md 导出带说话人真名）
- **本地运行**：录音与结果都存在你自己的机器，不上传任何服务器


## 功能一览
![详情页](docs/screenshot-detail.png)
围绕一段录音，听记给你四样东西——


**说话人自动分离 + 发言比例时间轴。** 顶部彩色横条按累计发言时长显示比例，一眼看出谁说得多；点说话人改成真名，改完同步到所有视图和导出。

**逐句时间戳，双击就改。** 点任意句定位音频，播放时当前句自动高亮 + 滚动跟随；识别错了双击直接改，可顺手加进热词，下次更准。
![原文 Tab：当前句高亮 + 双击编辑](docs/screenshot-edit.png)

**四段结构化会议纪要。** 整理完的总结自动拆成「概述 / 决议 / 待办 / 待讨论」，比一锅 Markdown 看着清楚；模型偶尔不吐严格 JSON 时回退成纯文本，不影响用。
![会议总结 Tab](docs/screenshot-summary.png)

**原文↔整理对照。** 左右双栏按时间戳对齐，hover 高亮、点击跳转音频、播放同步；整理偶尔会改原意，对照能快速核对。
![对照 Tab](docs/screenshot-compare.png)

整理前可配总结模板（普通会议 / 周会 / 访谈采访 / 项目管理，也可自定义），点「开始整理」时会先弹框让你选模板、填会议背景与术语。
![设置 → 总结模板](docs/screenshot-template.png)

处理日志记录各阶段耗时（详情页顶部展示总时长），落盘后重启可查。

## 环境要求

- macOS / Linux / Windows（WSL2）
- Python 3.11，用 [uv](https://github.com/astral-sh/uv) 管理
- ffmpeg（macOS：`brew install ffmpeg`；Linux：`sudo apt install ffmpeg`）
- Git LFS（用于预下载模型）
- 首次启动会下载约 1.3 GB FunASR 模型
- Windows 用户请看 [WSL2 + GPU 部署指南](docs/wsl-deploy.md)

## 快速开始

```bash
git clone https://github.com/baigong-ai/Tingji.git
cd Tingji
cp config.yaml.example config.yaml
cp .env.example .env          # api 模式时填入 LLM_API_KEY

bash scripts/download_models.sh   # 预下载模型（推荐）
./run.sh
```

浏览器打开 `http://127.0.0.1:8000`。

> 启动后会显示局域网地址，同一网络下的其他设备（手机/平板）也能打开使用。

### 常驻后台运行

```bash
./run.sh -d          # 后台运行（脱离终端，PID 写入 logs/tingji.pid，日志写入 logs/tingji.out）
./run.sh --status    # 看是否在跑
./run.sh --stop      # 停止
```

适合长时间挂在 Mac/Linux 上当本地转写服务用。「设置 → 服务」里还能改监听端口/host（改完需重启生效，改之前点「检测端口」，冲突会用 `lsof` 标出占用进程）。

#### 模型闲置自动卸载

常驻时最吃内存的是 FunASR 那 4 个模型。听记会在**闲置一段时间后把它们从内存里卸掉**，下次来活再自动加载——这样挂着不动时占用大幅下降。

**什么时候触发卸载**（必须同时满足）：
1. 模型当前已加载
2. 没有转录在进行（`is_busy=False`）
3. 没有任何任务在排队或跑（pending / converting / asr_running / 整理 / 总结 都不算空闲）
4. 距上次 ASR 活动时间 ≥ 阈值（默认 **30 分钟**，可在「设置 → 服务」改，**保存即生效**不用重启；设 0 = 从不卸载）

后台监视器每 60 秒查一次，所以最坏会多等 60 秒。急着释放可手点「设置 → 服务 → 立即释放模型」。

**两个平台的回收效果**（同一段 `test_cn.wav`，阈值 1 分钟实测）：

| 指标 | Mac mini M4 | WSL2 + RTX 4060 Ti |
|---|---|---|
| ASR 完成后 RSS | 1556 MB | 3521 MB |
| 卸载后 RSS | 1275 MB | 1843 MB |
| **RSS 净回收** | ~281 MB（**18%**） | **1678 MB（48%）** |
| GPU 显存回收 | —（无独立显卡） | 2222 → 948 MiB（**57%**） |

**为什么平台差距这么大**——两个独立因素叠加：
- **占用端**：WSL 走 CUDA 会把 CUDA runtime / cuDNN / cuBLAS 一坨库 + CUDA context 加载进进程，所以 ASR 时占用比 Mac（MPS，运行时由系统托管）高一倍多。模型本身两台机器一样大，差距在 GPU 后端依赖。
- **回收端**：Linux glibc 的 `free()` 配合 `malloc_trim(0)` 会把页**真正还给操作系统**（外加 `torch.cuda.empty_cache()` 还 GPU 显存）；macOS 的 malloc free 之后**不主动还页**，`ps` RSS 几乎不掉，但内存其实空出来了能被本进程复用。所以 Mac 上数字看着不动，实际进程内部已经可用。

判定"卸载有没有生效"别看 Mac 的 RSS 数字——看「设置 → 服务」的模型状态字段，或日志里的 `FunASR models unloaded (idle)`。

## 项目状态（v0.2）

核心链路可用：上传 → 识别（带说话人分离 + 时间戳）→ 校对 → 一键整理 + 结构化纪要。

**v0.2 新增（常驻后台能力）**：
- `./run.sh -d` 后台运行（`--status` / `--stop`，PID + 日志）
- **FunASR 模型闲置自动卸载**（默认 30 分钟，可配置；Mac 回收 18% / WSL+GPU 回收 48% RSS + 57% 显存）
- 「设置 → 服务」tab：ASR 模型状态 + 手动释放、端口/host 配置 + 冲突检测（lsof 反查）、闲置阈值
- `/api/asr/{status,unload}` 状态可观测 + 手动释放

**v0.1 已完成**：发言人时间轴、结构化纪要（概述 / 决议 / 待办 / 待讨论 四段 JSON）、总结模板（预设 + 自定义）、整理前会议背景与常用术语、说话人改名同步所有视图与导出、md / txt / srt 导出、实时日志（落盘 + 各阶段耗时）、固定布局（顶栏与工具栏不随滚动）。

**暂未做**：说话人手动合并 / 拆分、纪要二次编辑保存、docx 导出、导出选项（是否带说话人 / 时间戳）、议程章节切分。

## 使用流程

1. **上传录音**：拖入或选择音频文件，填写标题，点「开始转录」
2. **等待识别**：自动完成音频转换 + 语音识别，状态停在「待整理」
3. **校对原文**：在「原文」Tab 双击任意句子纠正错字（可顺手勾选「加入热词」），提升后续准确率
4. **一键整理**：点右上角「开始整理」（可先选总结模板、填会议背景与常用术语），自动生成整理稿与会议纪要

详情页顶部固定一条发言人时间轴 + 工具栏（搜索、Tab），只有内容区滚动。四个 Tab：

- **原文**：带说话人配色和时间戳，点击跳转音频
- **整理版**：去口语化的通顺文字
- **会议总结**：概述 / 决议 / 待办 / 待讨论（结构化四段；模型偶尔不吐严格 JSON 时回退成纯文本，不影响使用）
- **原文↔整理对照**：左右双栏按时间戳关联，hover 高亮、点击跳转音频、播放同步跟随

顶部可导出 `.md` / `.txt` / `.srt`；说话人 chip 点击改成真实名字。「重新整理」时会先让你选模板。

## 项目状态（v0.1）

核心链路可用：上传 → 识别（带说话人分离 + 时间戳）→ 校对 → 一键整理 + 结构化纪要。

**已完成**：发言人时间轴、结构化纪要（概述 / 决议 / 待办 / 待讨论 四段 JSON）、总结模板（预设 + 自定义）、整理前会议背景与常用术语、说话人改名同步所有视图与导出、md / txt / srt 导出、实时日志、固定布局（顶栏与工具栏不随滚动）。

**暂未做**：说话人手动合并 / 拆分、纪要二次编辑保存、docx 导出、导出选项（是否带说话人 / 时间戳）、议程章节切分。

## 预下载模型（推荐）

FunASR 需要 4 个模型（ASR / VAD / 标点 / 说话人），共约 1.3 GB。直接启动也能自动下载，但 macOS 上 uv 装的 Python 是临时签名，偶发网络受限。**启动前用 `git clone` 预下载更稳**（git 是 Apple 签名，走系统网络）。

```bash
bash scripts/download_models.sh          # 默认下载到 ./models/
# 或指定路径：
bash scripts/download_models.sh /path/to/models   # 并在 config.yaml 改 asr.cache_dir
```

手动 clone（目录名须严格对应）：

```bash
mkdir -p models && cd models && git lfs install
git clone --depth 1 https://www.modelscope.cn/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch.git paraformer-zh
git clone --depth 1 https://www.modelscope.cn/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch.git fsmn-vad
git clone --depth 1 https://www.modelscope.cn/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch.git ct-punc
git clone --depth 1 https://www.modelscope.cn/iic/speech_campplus_sv_zh-cn_16k-common.git campp
```

## 配置

绝大多数配置都能在网页「设置」里完成（数据目录 / LLM / 热词）。需要时也可直接编辑 `config.yaml`：

| 字段 | 说明 |
|---|---|
| `asr.cache_dir` | FunASR 模型缓存目录，默认 `./models` |
| `asr.hub` | `ms`（ModelScope，默认）或 `hf` |
| `asr.idle_unload_minutes` | 模型闲置多久后自动卸载（分钟），默认 30；0 = 从不。可在网页「设置 → 服务」改，即时生效 |
| `llm.mode` | `api` 或 `ollama` |
| `llm.api.*` | OpenAI 兼容 API（base_url / api_key / model） |
| `llm.ollama.*` | 本地 Ollama（base_url / model） |
| `llm.polish_chunk_minutes` | 整理分段时长（分钟），默认 6 |

`api_key` 支持 `${LLM_API_KEY}` 占位，从环境变量读取。

### LLM 示例

**Ollama 本地：**
```bash
ollama pull qwen2.5:7b && ollama serve
# config.yaml: llm.mode: ollama
```

**DeepSeek：**
```yaml
llm:
  mode: api
  api: { base_url: "https://api.deepseek.com/v1", api_key: "${LLM_API_KEY}", model: "deepseek-chat" }
```

**通义千问：**
```yaml
llm:
  mode: api
  api: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key: "${LLM_API_KEY}", model: "qwen-plus" }
```

### 模型选择

模型选哪个看你的硬件和偏好，这里不替你选，只列实测过的：

- **本地 Ollama**：`Qwen3:8b`（gguf；WSL + RTX 4060 Ti、Mac mini M4 均实测可用）
- **API（OpenAI 兼容）**：GLM、DeepSeek

Qwen3 的 thinking 已经在代码里关掉（`/no_think`），不然会很慢。

## 性能参考

- 81 分钟访谈（GPU：RTX 4060 Ti）：识别约 2 分钟（RTF ≈ 0.025），完整流程约 7–8 分钟
- CPU 模式：约音频时长 × 0.25（60 分钟音频 ≈ 15 分钟）
- 支持 60–90 分钟长音频（VAD 自动切片 + 分批推理）

## 已知限制

- 说话人分离基于音色聚类，设备/位置变化可能导致 ID 拆分或合并
- LLM 整理可能轻微改变原意，可用「对照」Tab 核对
- 无用户认证，仅适合本地或可信局域网运行
- 进行中的任务状态存内存，重启服务会丢失（已完成会议数据在磁盘上）

## 项目结构

```
app/
  config.py   配置加载（${ENV_VAR} 展开）
  audio.py    ffmpeg 转换
  asr.py      FunASR AutoModel 封装（GPU 优先）
  llm.py      整理 + 总结（分段 + map-reduce）
  storage.py  data/ 目录 CRUD
  tasks.py    异步 pipeline + 进度
  main.py     FastAPI 路由
static/       首页 / 详情页 / 样式
data/         会议数据（gitignore）
models/       FunASR 模型缓存（gitignore）
test/         单元测试 + 冒烟脚本
```

## License

MIT
