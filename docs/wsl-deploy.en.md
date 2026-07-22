# Windows + WSL2 + GPU Deployment Guide

This guide covers deploying the FunASR meeting transcription system on Windows 11 via WSL2, with NVIDIA GPU acceleration.

## 1. Prerequisites

### Windows version

Windows 10 21H2+ / Windows 11. WSL2 requires kernel 5.10+.

### GPU (optional but strongly recommended)

- NVIDIA GPU, VRAM >= 6GB (paraformer-zh + cam++ peaks around 4GB)
- Install the **Windows** NVIDIA driver (>= 535). The driver lives on Windows and is passed through to WSL2 automatically — **do not** install a separate CUDA driver inside WSL
- Verify passthrough: run `nvidia-smi` inside WSL; if you see the GPU and driver version, you're good

## 2. Install WSL2 + Ubuntu

Open PowerShell as admin:

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

Reboot, enter Ubuntu, set username/password.

Confirm it's WSL2 (not WSL1):

```powershell
wsl -l -v
# VERSION column must be 2
```

## 3. Base environment inside WSL

In the Ubuntu shell:

```bash
sudo apt update
sudo apt install -y ffmpeg git git-lfs
git lfs install

# Python 3.11 (Ubuntu 22.04 ships 3.10; install 3.11 explicitly)
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

## 4. Clone the repo + download models

```bash
git clone https://github.com/baigong-ai/Tingji.git funasr
cd funasr

cp config.yaml.example config.yaml
# make sure server.host is "0.0.0.0" (it is by default)

bash scripts/download_models.sh   # ~1.3GB via git, reliable
```

## 5. Install CUDA-enabled PyTorch

`pyproject.toml` pulls the CPU build of torch by default. To use the GPU you must override it:

```bash
uv venv --python 3.11
source .venv/bin/activate

# install the rest of the project deps first (pulls CPU torch)
uv pip install -e .

# then override with the CUDA 12.1 build
uv pip install --reinstall \
  torch torchaudio \
  --index-url https://download.pytorch.org/whl/cu121
```

If your CUDA version isn't 12.1, look up the matching wheel at https://pytorch.org/get-started/locally/. Common mapping:

| Windows driver CUDA | torch index-url |
|---|---|
| 12.1 - 12.6 | `cu121` (compatible) |
| 11.8 | `cu118` |

Verify the GPU is available:

```bash
python -c "import torch; print('cuda:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu')"
```

Expected: `cuda: True | NVIDIA GeForce RTX xxxx`

## 6. Start the service

```bash
./run.sh
```

The startup log shows the device, e.g.:

```
loading FunASR models from ./models (hub=ms, device=cuda:0)...
```

If you see `device=cpu`, torch isn't the CUDA build — go back to step 5.

## 7. Live streaming transcription (v0.4)

WSL + GPU supports both realtime modes:

| Mode | Description | Extra service required |
|---|---|---|
| **Standard** | Built-in `paraformer-zh-streaming` engine, works out of the box | No |
| **Enhanced** | Forwards to a Fun-ASR-Nano vLLM GPU sidecar, better for dialects / accents / far-field | Yes — sidecar must be started separately |

Standard mode needs no configuration; click "Live" on the home page to start.

### Enhanced mode sidecar deployment

Enhanced mode requires a separate GPU sidecar service, default `ws://localhost:10095`.

**Requirements (higher than the main project)**:
- CUDA 12.6+ (Fun-ASR-Nano currently needs torch>=2.9 and vllm>=0.12)
- NVIDIA dGPU with 8GB+ VRAM (12GB+ recommended)
- ~2.1GB extra model download (`FunAudioLLM/Fun-ASR-Nano-2512`)

**Example deployment** (use a separate directory to avoid dependency conflicts with the main project):

```bash
cd ~
git clone --depth 1 https://github.com/FunAudioLLM/Fun-ASR.git
git clone --depth 1 https://github.com/modelscope/FunASR.git FunASR-git

mkdir -p funasr-sidecar && cd funasr-sidecar
uv venv --python 3.12
source .venv/bin/activate

# Install CUDA 12.6 torch (adjust index-url to your CUDA version)
uv pip install torch==2.9.0+cu126 torchaudio==2.9.0+cu126 \
  --index-url https://download.pytorch.org/whl/cu126

# Install vllm, funasr from source, and dependencies
uv pip install 'vllm>=0.12.0' websockets regex
uv pip install -e ~/FunASR-git

# Start the sidecar (loads ~2.1GB model)
export PYTHONPATH="$HOME/FunASR-git:$PYTHONPATH"
python ~/Fun-ASR/serve_realtime_ws.py \
  --port 10095 --device cuda:0 --gpu-memory-utilization 0.6 --disable-spk
```

**Switch Tingji to Enhanced mode**:

Edit `config.yaml`:

```yaml
asr:
  stream_engine: sidecar
  sidecar_url: ws://localhost:10095
```

Or switch via "Settings → ASR" if the UI exposes it.

> Note: if your WSL environment is currently CUDA 12.1 + torch 2.5, the Fun-ASR-Nano vLLM sidecar will not run; upgrade the CUDA toolkit to 12.6+ and install matching torch/vllm first.

## 8. Access the service

### From the Windows host

WSL2 forwards the service port to Windows localhost by default. Open in your browser:

```
http://localhost:8000
```

The "Access addresses" card at the top of the home page shows the URL — copy and use.

### From other machines on the LAN

WSL2 runs in NAT mode, so LAN machines can't reach WSL by default. You need to set up a portproxy on **Windows**. Open PowerShell as admin:

```powershell
# find the WSL IP
wsl hostname -I
# e.g. 172.20.50.123

# set portproxy (fill in the IP above)
netsh interface portproxy add v4tov4 `
  listenport=8000 listenaddress=0.0.0.0 `
  connectport=8000 connectaddress=172.20.50.123

# open firewall port 8000
New-NetFirewallRule -DisplayName "FunASR WSL" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 8000

# show rules
netsh interface portproxy show v4tov4
```

Then access from other machines at `http://<Windows-host-IP>:8000`.

Note: WSL's IP may change on each restart; you may need to reset the portproxy. You can script it to run on boot.

### Find the Windows host IP

```powershell
ipconfig | findstr IPv4
```

## 9. Performance

GPU inference speed (measured on RTX 4060 Ti, 81-min Chinese audio):

- ASR (paraformer + VAD + cam++): ~2 min (RTF ≈ 0.025, ~40x realtime)
- LLM polish + summary: depends on the LLM backend
  - Local Ollama (Qwen3:8b gguf): ~5-8 min
  - API (GLM/DeepSeek): 1-2 min
  - **Don't use `*-mlx` on WSL/NVIDIA**: mlx is an Apple Silicon-only backend; on NVIDIA/WSL the backend mismatches (won't run, not a perf issue) — use gguf builds

Total ~7-10 min. CPU-mode ASR is far slower (RTF ≈ 0.25, ~1/4 of audio length); use GPU for long audio.

> Note: `app/asr.py` must pass `device` explicitly to the FunASR `AutoModel`, otherwise even with the CUDA torch build it defaults to CPU (RTF shoots past 4).

## 10. Troubleshooting

### `nvidia-smi` not found inside WSL

- Windows NVIDIA driver too old — upgrade to latest
- WSL kernel too old — `wsl --update`
- Confirm WSL2 not WSL1: `wsl -l -v`

### torch.cuda.is_available() returns False

- `nvidia-smi` works but torch doesn't → torch is the CPU build
- Fix: `uv pip install --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu121`
- Don't use `sudo`; don't mix system Python and the venv

### funasr stuck on "loading models"

Models didn't download completely. Check `du -sh models/*` — paraformer-zh should be ~950MB. If it's only a few KB, re-run `bash scripts/download_models.sh`.

### LAN access 404 / timeout

- `curl http://localhost:8000` works inside WSL → service is fine
- `curl http://localhost:8000` works in Windows PowerShell → WSL→Windows forwarding is fine
- LAN machine can't connect → portproxy or firewall is off; see section 7

### Reset everything

```powershell
wsl --shutdown   # stop all WSL instances
# inside WSL: rm -rf funasr/.venv funasr/models
```
