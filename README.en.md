English | [中文](README.md)

# Tingji (听记)

> Local meeting transcription and minutes — drop in a recording and get the raw transcript, a cleaned-up transcript, and meeting minutes. All data stays on your own machine.

![Home](docs/screenshot-home.png)

Built on [FunASR](https://github.com/modelscope/FunASR) (speech recognition + speaker diarization + punctuation) and an LLM for cleanup. Great for long-form audio — meetings, interviews, lectures. Cross-platform (macOS / Windows WSL2 + GPU); recognition runs offline.

## Features

- **Automatic speaker diarization** — CAM++ voice clustering tells "who is speaking"; rename to real names, synced across all views and exports
- **Speaker timeline** — a proportional bar at the top showing each speaker's share of talk time; click to jump to their first utterance, highlights the active speaker during playback
- **Per-sentence timestamps** — click any sentence to seek the audio (without forcing playback); the current sentence auto-highlights and scrolls during playback
- **Timestamped minutes (v0.7)** — decisions / action items / open questions can each carry an `[m:ss]` chip; click it to jump back to that exact moment in the audio. Polished-section headings carry the utterance start time too, and exported minutes keep the timestamps inline
- **Personal notes layer (v0.7)** — hover any raw sentence and hit ✎ to attach your own note; notes are anchored to sentences and stored separately in `notes.json`, so re-running the polish never overwrites them. A "My notes" panel on the summary tab lists them chronologically with jump-to-sentence chips; unanchored global notes are supported too, and minutes export can append a Personal notes section
- **Topic timeline (v0.7)** — a second timeline under the speaker bar splits the meeting into topic segments (background / question / discussion / conclusion / action / small-talk); click a segment to jump, playback highlights the current topic. The LLM proposes segments, humans can correct them (rename / rephase / adjust boundary / delete), and manual edits survive re-running the polish
- **Raw ↔ polished compare** — side-by-side columns aligned by timestamp; hover highlights, click seeks, playback stays in sync
- **Manual correction + hotwords** — double-click a sentence to fix recognition errors; optionally add it as a hotword to improve accuracy next time
- **One-click polish** — turns colloquial raw text into fluent prose, then generates structured minutes (summary / decisions / action items / open questions); optionally pick a summary template and fill in meeting background + common terms first
- **Summary templates** — built-in General / Weekly / Interview / Project, plus custom (background, common terms, summary direction / content / framework) for different meeting types
- **Live log** — progress bar + ASR device (GPU name) / model / per-chunk timing; warns when nothing updates for >15s so you can tell if it's stuck
- **Bring-your-own LLM** — local Ollama, or any OpenAI-compatible API (GLM / DeepSeek / Qwen / Kimi / OpenAI …)
- **Configure everything in the browser** — data directory, LLM, hotwords, summary templates are all set via the web UI, no file editing
- **Export** `.md` / `.txt` / `.srt` (md export uses real speaker names)
- **Live streaming transcription** — open the microphone during a meeting; when stopped or disconnected, the transcript + audio are saved and shown immediately, then a background second pass upgrades them with accurate timestamps and speaker labels; after that, the same proofread → polish → summarize pipeline as uploads. Standard mode (built-in engine, all platforms). Enhanced mode (GPU engine) is shelved for now; the live page ships Standard mode only
- **Meeting library management** — tag meetings and filter by tag, rename any finished meeting, delete to trash or permanently; the trash view can restore or permanently delete
- **Edit the minutes afterwards** — both the polished text and the summary can be edited and saved (the summary supports per-section structured editing as well as plain markdown)
- **Resume stuck tasks** — if a restart leaves a task stuck, click "Resume task" on the detail page; an optional hourly cron can do it automatically
- **Runs locally** — recordings and results never leave your machine



## A quick look
![Detail page](docs/screenshot-detail.png)
Around a single recording, Tingji gives you four things:

**Automatic speaker diarization + talk-time timeline.** A colored bar at the top shows each speaker's share of total talk time — who talked more at a glance. Rename to real names, synced across all views and exports.

**Per-sentence timestamps, double-click to fix.** Click any sentence to seek the audio; the current sentence auto-highlights and scrolls during playback. Double-click to correct a misrecognition, optionally adding it as a hotword for next time.
![Raw tab: current sentence highlighted, double-click to edit](docs/screenshot-edit.png)

**Structured minutes in four parts.** The summary is split into Overview / Decisions / Action items / Open questions — clearer than a wall of Markdown. Falls back to plain text if the model doesn't return strict JSON; still usable.
![Summary tab](docs/screenshot-summary.png)

**Minutes that lead back to the moment, notes that survive (v0.7).** Every decision and action item can carry an `[m:ss]` chip that seeks the audio to the exact sentence; hover a raw sentence and hit ✎ to jot a margin note stored separately from the AI output; a topic timeline above the transcript shows how the meeting unfolded (question → discussion → conclusion → action), each segment clickable.

**Raw ↔ polished compare.** Side-by-side columns aligned by timestamp; hover highlights, click seeks, playback stays in sync. Quick to spot when the LLM has subtly changed the meaning.
![Compare tab](docs/screenshot-compare.png)

Before polishing you can pick a summary template (General / Weekly / Interview / Project, all customizable) — the dialog asks for the template plus any meeting background and terminology.
![Settings → Summary templates](docs/screenshot-template.png)

Per-stage processing time is logged (total shown in the detail-page header) and persisted, so history survives a restart.

## Requirements

- macOS / Linux / Windows (WSL2)
- Python 3.11, managed with [uv](https://github.com/astral-sh/uv)
- ffmpeg (`brew install ffmpeg` on macOS; `sudo apt install ffmpeg` on Linux)
- Git LFS (for pre-downloading models)
- First launch downloads ~1.3 GB of FunASR models
- Windows users: see the [WSL2 + GPU deployment guide](docs/wsl-deploy.en.md)

## Quick start

```bash
git clone https://github.com/baigong-ai/Tingji.git
cd Tingji
cp config.yaml.example config.yaml
cp .env.example .env          # fill in LLM_API_KEY when using api mode

bash scripts/download_models.sh   # pre-download models (recommended)
./run.sh
```

Open `http://127.0.0.1:8000` in your browser.

> On launch it prints the LAN address too — other devices on the same network (phone/tablet) can use it as well.

### Running as a background service

```bash
./run.sh -d          # background (detached; PID → logs/tingji.pid, log → logs/tingji.out)
./run.sh --status    # is it running?
./run.sh --stop      # stop
```

Handy for keeping Tingji resident on a Mac/Linux box as your local transcription service. Settings → Service also lets you change the listen port/host (restart required) — click "Check port" first and it'll name the conflicting process via `lsof` if the port is taken.

#### Auto-resume interrupted tasks (optional)

A restart leaves in-flight tasks stuck in an intermediate status. Besides the manual "Resume task" button on the detail page, you can install an hourly cron to resume them automatically (live meetings interrupted by a restart recover recognition from the saved audio; those without saved audio are marked as failed):

```bash
crontab -l | { cat; echo '17 * * * * cd /path/to/Tingji && .venv/bin/python scripts/resume_tasks.py >> logs/resume.log 2>&1'; } | crontab -
```

The script reads port / SSL / data dir from `config.yaml`, so custom configurations work out of the box.

#### Idle model auto-unload

The biggest resident cost is the 4 FunASR models. After an idle period Tingji **unloads them from RAM** and reloads on the next transcription — so the resident footprint drops sharply when nothing's happening.

**Unload fires when all of these hold**:
1. The model is currently loaded
2. No transcription is in flight (`is_busy=False`)
3. No task is queued or running (pending / converting / asr_running / polish / summarize don't count as idle)
4. Time since the last ASR activity ≥ threshold (default **30 min**; set in Settings → Service, **takes effect on save** without a restart; 0 = never unload)

A watcher checks every 60 s, so worst case add ~60 s. In a hurry, hit "Release model now" in Settings → Service.

**Reclaim by platform** (same `test_cn.wav`, 1-minute threshold):

| Metric | Mac mini M4 | WSL2 + RTX 4060 Ti |
|---|---|---|
| RSS right after ASR | 1556 MB | 3521 MB |
| RSS after unload | 1275 MB | 1843 MB |
| **RSS net reclaimed** | ~281 MB (**18%**) | **1678 MB (48%)** |
| GPU memory reclaimed | — (no dGPU) | 2222 → 948 MiB (**57%**) |

**Why the platform gap** — two independent factors stack:
- **Occupation side**: on WSL+CUDA the process pulls in the CUDA runtime + cuDNN + cuBLAS + a CUDA context, so peak RSS is ~2× the Mac (MPS) where the runtime is mostly system-shared. The models themselves are identical; the difference is the GPU backend's dependencies.
- **Reclaim side**: Linux glibc's `free()` + `malloc_trim(0)` actually **returns pages to the OS** (plus `torch.cuda.empty_cache()` for VRAM); macOS's malloc **doesn't proactively return** freed pages, so `ps` RSS barely moves even though the memory is reusable in-process.

Don't judge "did unload work" by macOS RSS — check the model-state field in Settings → Service, or the `FunASR models unloaded (idle)` log line.

## Project status (v0.7.1)

The core pipeline works: upload → recognition (with speaker diarization + timestamps) → proofread → one-click polish + structured minutes (items timestamped) + topic timeline + personal notes; the meeting library supports tags, rename, delete, and trash restore; live streaming transcription (standard mode) is available.

**New in v0.7.1 (live-save reliability)**:
- **Transcript the moment the meeting ends** — when a live session stops or the connection drops, the audio + streaming transcript are saved and shown immediately; an offline second pass then runs in the background (status shows "Recognizing") and the page auto-reloads with the refined transcript (accurate timestamps + speaker labels) when it finishes. The proofread → polish → summarize flow is unchanged
- **Fixed: meetings stuck in "live" after the meeting ended** — the meeting status used to update only after the offline second pass finished (including a multi-minute cold model load; GPU stalls could stretch this to ten-plus minutes), leaving the detail page empty in the meantime as if the record was lost, and a wedged recognition stalled the status forever. Status now settles within seconds, decoupled from the slow recognition
- **Failure fallback** — if the second pass fails or times out, the streaming transcript is kept and "Resume task" on the detail page re-runs it; live meetings interrupted by a service restart recover recognition from the saved audio on disk instead of always reporting "recording lost"

**New in v0.7 (the after-meeting layer: traceability, notes, topics)**:
- **Timestamped minutes** — polished headings carry `[m:ss]` anchors; decisions / action items / open questions carry clickable timestamp chips that seek the audio; exports keep them inline. Items without timestamps (weak local models, older meetings) degrade gracefully
- **Personal notes** — anchored margin notes on raw sentences plus unanchored global notes, stored in a separate `notes.json` that re-polish never touches; "My notes" panel with jump chips; minutes export can append a Personal notes section (`notes=false` to omit)
- **Topic timeline** — LLM-proposed topic segments (background / question / discussion / conclusion / action / small-talk) with click-to-jump and playback highlight; manual rename / rephase / boundary / delete, and manual edits are protected from regeneration; long meetings are segmented per ~25-minute windows then merged
- **Enhanced mode (GPU sidecar) shelved** — the live page no longer renders the engine picker; the backend still rejects `sidecar`

**New in v0.6 (offline core)**: batch upload + queue, manual speaker merge/split (pure metadata remap), docx export for polished text and minutes, export options (speaker/timestamps on/off), proofreading aids (speed control + silence skip), pipeline unlock (parallel convert/polish across files), polish quality guards (echo detection / thinking toggle).

**New in v0.5 (stability + trash + minutes editing)**:
- **Trash management** — a Trash dialog on the home page lists deleted meetings with one-click restore and permanent delete (the v0.3 "recoverable" promise now has a UI)
- **Edit the minutes** — both the polished text and the summary can be edited and saved; the summary supports per-section editing (overview / decisions / action items / open questions) as well as plain markdown
- **Resume stuck tasks** — a "Resume task" button on the detail page; `scripts/resume_tasks.py` runs as an hourly cron and reads port / SSL / data dir from config.yaml
- **Stability fixes** — a bug where retried tasks stayed "queued" forever (and blocked idle model unload), the punctuation model stalling all HTTP during live sessions, stuck status after interrupted polish, atomic + fault-tolerant `meta.json` writes, meeting_id path-traversal hardening
- **Security** — speaker-name injection XSS fixed; Enhanced mode (GPU sidecar) rejected server-side (later shelved, see v0.7)

**New in v0.4 (live streaming transcription)**:
- **Live streaming transcription** — open the microphone during a meeting; when stopped it automatically writes `audio_live.wav` + `raw.json` and enters the "Ready to polish" state, after which the proofread / polish / summarize flow is identical to the upload path
- **Standard mode** — built-in FunASR streaming engine (`paraformer-zh-streaming`); works on macOS / WSL / Linux with no extra setup
- **Enhanced mode (GPU engine)** — was planned to forward audio to a Fun-ASR-Nano vLLM GPU sidecar (`ws://localhost:10095`) for better accuracy on dialects, accents, and far-field audio; shelved as of v0.7 (implementation kept in `app/stream.py`)
- **Unified entry point** — "Live" tab on the home page

**v0.3 done (meeting library)**:
- **Tags + filter** — add multiple tags to a meeting, filter the list by tag (multi-select union); click a tag chip on a row to filter too
- **Rename** — finished meetings (Ready to polish / Done / Error) can be renamed
- **Two delete modes** — move to trash (`data/回收站/`, files kept and recoverable) or delete permanently; the trash path is shown before deleting
- **Persistent onboarding** — the "Recordings will be saved to…" banner is saved to config.yaml once confirmed, so it no longer reappears when you switch browsers or clear cache

**v0.2 resident mode**: `./run.sh -d` background running; FunASR model auto-unloads when idle (default 30 min, configurable; reclaims 18% RSS on Mac / 48% RSS + 57% VRAM on WSL+GPU); Settings → Service tab (model status/release, port/host + conflict detection, idle threshold).

**v0.1 done**: speaker timeline, structured minutes (summary / decisions / action items / open questions as JSON), summary templates (preset + custom), pre-polish meeting background + common terms, speaker rename synced across views and exports, md / txt / srt export, live log, fixed layout.

**Not yet**: meeting-content Q&A, component-based minutes (tables / columns / process bars), static HTML page export.

## Live transcription

In addition to "upload a recording then process it", Tingji supports live microphone transcription during meetings. When stopped or disconnected, the audio + streaming transcript are saved and shown immediately, with nothing to wait for; a background second pass then upgrades them with accurate timestamps and speaker labels and the page auto-reloads, after which the same proofread → polish → summarize pipeline as uploads applies.

One engine ships today:

| Mode | Name | Platforms | Hardware requirements |
|---|---|---|---|
| **Standard** | Built-in realtime engine | macOS / WSL / Linux | Apple Silicon M1+ or modern CPU, 8GB+ RAM |

- **Standard mode** is the default and works on every platform without extra setup.
- **Enhanced mode** (GPU engine, for dialects / accents / far-field) is shelved: it needs a separate Fun-ASR-Nano vLLM GPU sidecar (`ws://localhost:10095`, WSL/Linux + NVIDIA dGPU only), a heavy deployment. As of v0.7 the live page no longer renders the engine picker and the backend rejects `sidecar`. The implementation is kept in `app/stream.py` and may return someday.

### HTTPS for LAN access (live mic)

Browsers only allow microphone access in a secure context (localhost or HTTPS). To use live transcription from another device on the LAN:

1. Edit `config.yaml`:

```yaml
server:
  ssl:
    enabled: true
```

2. Restart the service. `run.sh` will automatically generate a self-signed certificate at `certs/cert.pem` and `certs/key.pem`.
3. On the LAN device, open `https://<server-ip>:8000/live`.
4. The first time, the browser will warn about the self-signed certificate. Click "Advanced" → "Proceed" (on iOS Safari, go to Settings → General → About → Certificate Trust Settings and trust the certificate).

> Self-signed certificates are intended for LAN use only. Do not expose them to the public internet or commit them (`certs/` is in `.gitignore`).

## Workflow

1. **Upload** — drag in an audio file, enter a title, click "Start transcription"
2. **Wait for recognition** — audio conversion + ASR run automatically; status stops at "Ready to polish"
3. **Proofread** — on the "Raw" tab, double-click any sentence to correct it (optionally "add as hotword") to improve later accuracy
4. **Polish** — click "Start polish" in the top right (optionally pick a summary template and fill in meeting background + common terms first) to generate the cleaned transcript and minutes

The detail page has a fixed speaker timeline + toolbar (search, tabs) at the top; only the content area scrolls. Four tabs:

- **Raw** — color-coded speakers + timestamps; click to seek audio
- **Polished** — de-colloquialized, fluent text
- **Summary** — summary / decisions / action items / open questions (structured; falls back to plain text if the model doesn't return strict JSON — still usable)
- **Compare** — raw vs. polished side by side, aligned by timestamp; hover highlights, click seeks, playback follows

Export `.md` / `.txt` / `.srt` from the top bar; click a speaker chip to rename it. "Re-polish" asks you to pick a template first.

## Pre-downloading models (recommended)

FunASR needs 4 models (ASR / VAD / punctuation / speaker), ~1.3 GB total. Direct launch also works, but on macOS the uv-installed Python is temporarily signed and occasionally hits network limits. **Pre-downloading with `git clone` is more reliable** (git is Apple-signed and uses the system network path).

```bash
bash scripts/download_models.sh          # downloads to ./models/ by default
# or a custom path:
bash scripts/download_models.sh /path/to/models   # then set asr.cache_dir in config.yaml
```

Manual clone (directory names must match exactly):

```bash
mkdir -p models && cd models && git lfs install
git clone --depth 1 https://www.modelscope.cn/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch.git paraformer-zh
git clone --depth 1 https://www.modelscope.cn/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch.git fsmn-vad
git clone --depth 1 https://www.modelscope.cn/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch.git ct-punc
git clone --depth 1 https://www.modelscope.cn/iic/speech_campplus_sv_zh-cn_16k-common.git campp
```

## Configuration

Almost everything is configurable from the in-browser "Settings" (data directory / LLM / hotwords). You can also edit `config.yaml` directly:

| Field | Description |
|---|---|
| `asr.cache_dir` | FunASR model cache dir, default `./models` |
| `asr.hub` | `ms` (ModelScope, default) or `hf` |
| `asr.idle_unload_minutes` | Minutes of idle before the model auto-unloads from RAM (default 30; 0 = never). Set in Settings → Service; takes effect immediately |
| `llm.mode` | `api` or `ollama` |
| `llm.api.*` | OpenAI-compatible API (base_url / api_key / model) |
| `llm.ollama.*` | Local Ollama (base_url / model / think) |
| `llm.polish_chunk_minutes` | chunk length for polishing (minutes), default 6 |

`api_key` supports a `${LLM_API_KEY}` placeholder read from the environment.

### LLM examples

**Local Ollama:**
```bash
ollama pull qwen2.5:7b && ollama serve
# config.yaml: llm.mode: ollama
```

**DeepSeek:**
```yaml
llm:
  mode: api
  api: { base_url: "https://api.deepseek.com/v1", api_key: "${LLM_API_KEY}", model: "deepseek-chat" }
```

**Qwen:**
```yaml
llm:
  mode: api
  api: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key: "${LLM_API_KEY}", model: "qwen-plus" }
```

### Model selection

**Local-first is a core principle of this project**: ASR runs entirely on-device, and polish/summarize default to local Ollama too — meeting content never leaves your machine. Online APIs are an optional enhancement for cases where local models fall short.

Pick based on your hardware and preference — this doc doesn't pick for you, just lists what's been tested:

- **Local Ollama**: `Qwen3:8b` (gguf; tested on WSL + RTX 4060 Ti and Mac mini M4)
- **API (OpenAI-compatible)**: GLM, DeepSeek

Reasoning on thinking models (Qwen3 family etc.) is controlled by the "thinking mode" toggle on the settings page (`ollama.think`, via the Ollama native API `think` field): off is fast but small models may just echo the transcript; on is more accurate but slower. **Recommended ON when polishing with local Qwen3.** Runaway reasoning that returns empty content is retried as a failure with the raw transcript kept as fallback. When a polished draft is nearly identical to the transcript, the detail page shows a warning banner suggesting a stronger model or enabling thinking.

## Performance

- 81-min interview (GPU: RTX 4060 Ti): ASR ~2 min (RTF ≈ 0.025), full pipeline ~7–8 min
- CPU mode: roughly audio-length × 0.25 (60-min audio ≈ 15 min)
- Supports 60–90 min long audio (auto VAD chunking + batched inference)

## Known limitations

- Speaker diarization is voice-clustering based; device/position changes can split or merge speaker IDs
- LLM cleanup may slightly alter meaning — use the "Compare" tab to verify
- No authentication — suitable only for local or trusted-LAN use
- In-flight task state lives in memory and is lost on restart (finished meetings persist on disk)

## Project structure

```
app/
  config.py   config loading (${ENV_VAR} expansion)
  audio.py    ffmpeg conversion
  asr.py      FunASR AutoModel wrapper (GPU-first)
  stream.py   realtime streaming engine (standard funasr; enhanced sidecar kept but shelved)
  llm.py      polish + summarize (chunking + map-reduce)
  storage.py  data/ directory CRUD (meetings / notes / topics / templates / logs)
  tasks.py    async pipeline + progress
  main.py     FastAPI routes
  dns_hosts.py optional DNS override (active when dns_hosts.txt exists)
static/       home / detail / live pages (index / meeting / live)
data/         meeting data (gitignored)
models/       FunASR model cache (gitignored)
test/         unit tests + smoke scripts
```

## License

MIT
