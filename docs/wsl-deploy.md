# Windows + WSL2 + GPU 部署指南

本文档说明在 Windows 11 上通过 WSL2 部署 FunASR 会议转录系统，并用 NVIDIA GPU 加速推理。

## 1. 前置检查

### Windows 版本

Windows 10 21H2 及以上 / Windows 11。WSL2 需要内核版本 5.10+。

### GPU（可选但强烈推荐）

- NVIDIA GPU，显存 >= 6GB（运行 paraformer-zh + cam++ 峰值约 4GB）
- 装好 **Windows 版** NVIDIA 驱动（>= 535）。驱动走 Windows，WSL2 自动直通，**不要**在 WSL 里单独装 CUDA 驱动
- 验证驱动直通成功：在 WSL 里跑 `nvidia-smi`，能看到 GPU 和驱动版本就 OK

## 2. 安装 WSL2 + Ubuntu

以管理员身份开 PowerShell：

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

重启后进入 Ubuntu，设置用户名密码。

确认是 WSL2（不是 WSL1）：

```powershell
wsl -l -v
# VERSION 列必须是 2
```

## 3. WSL 内的基础环境

在 Ubuntu shell 里：

```bash
sudo apt update
sudo apt install -y ffmpeg git git-lfs
git lfs install

# Python 3.11（Ubuntu 22.04 自带 3.10，需要额外装 3.11）
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

## 4. 拉代码 + 下载模型

```bash
git clone <repo> funasr
cd funasr

cp config.yaml.example config.yaml
# 确认 server.host 是 "0.0.0.0"（默认就是）

bash scripts/download_models.sh   # 约 2.5GB，走 git，可靠
```

## 5. 装 CUDA 版 PyTorch

`pyproject.toml` 默认拉的是 CPU 版 torch。要用 GPU 必须覆盖：

```bash
uv venv --python 3.11
source .venv/bin/activate

# 先装项目其余依赖（会装 CPU 版 torch）
uv pip install -e .

# 再用 CUDA 12.1 版 torch 覆盖
uv pip install --reinstall \
  torch torchaudio \
  --index-url https://download.pytorch.org/whl/cu121
```

如果你的 CUDA 版本不是 12.1，去 https://pytorch.org/get-started/locally/ 查对应 wheel。常见映射：

| Windows 驱动 CUDA | torch index-url |
|---|---|
| 12.1 - 12.6 | `cu121`（兼容） |
| 11.8 | `cu118` |

验证 GPU 可用：

```bash
python -c "import torch; print('cuda:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu')"
```

期望输出：`cuda: True | NVIDIA GeForce RTX xxxx`

## 6. 启动服务

```bash
./run.sh
```

启动日志里会看到设备信息，例如：

```
loading FunASR models from ./models (hub=ms, device=cuda (NVIDIA GeForce RTX 4070))...
```

如果看到 `device=cpu`，说明 torch 没装 CUDA 版，回到第 5 步。

## 7. 访问服务

### 从 Windows 本机

WSL2 默认会把服务端口转发到 Windows 的 localhost。直接在浏览器开：

```
http://localhost:8000
```

首页顶部"访问地址"卡片会显示 URL，复制即用。

### 从局域网其他机器

WSL2 是 NAT 模式，局域网机器默认访问不到 WSL。需要在 **Windows** 上开 portproxy。以管理员身份开 PowerShell：

```powershell
# 查 WSL 子系统的 IP
wsl hostname -I
# 输出例如: 172.20.50.123

# 设 portproxy（把上面的 IP 填进去）
netsh interface portproxy add v4tov4 `
  listenport=8000 listenaddress=0.0.0.0 `
  connectport=8000 connectaddress=172.20.50.123

# 防火墙开 8000
New-NetFirewallRule -DisplayName "FunASR WSL" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 8000

# 查看已设规则
netsh interface portproxy show v4tov4
```

然后在其他机器用 `http://<Windows主机IP>:8000` 访问。

注意：WSL 每次重启 IP 可能变化，重启后可能需要重设 portproxy。可以写成开机脚本。

### 查 Windows 主机 IP

```powershell
ipconfig | findstr IPv4
```

## 8. 性能参考

GPU 推理速度参考（RTX 4070，60 分钟中文音频）：

- ASR（paraformer + VAD + cam++）：约 2-3 分钟
- LLM 整理 + 总结：取决于 LLM 后端
  - 本地 Ollama（Qwen3:8b）：约 5-8 分钟
  - API（GLM/DeepSeek）：1-2 分钟

总耗时约 5-10 分钟，比 CPU（15-20 分钟）快 2-3 倍。

## 9. 故障排查

### `nvidia-smi` 在 WSL 里找不到

- Windows NVIDIA 驱动版本太旧，升级到最新
- WSL 内核太旧，`wsl --update`
- 确认是 WSL2 不是 WSL1：`wsl -l -v`

### torch.cuda.is_available() 返回 False

- `nvidia-smi` 通了但 torch 不行 → torch 装成了 CPU 版
- 解决：`uv pip install --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu121`
- 别用 `sudo`，别混系统 Python 和 venv

### funasr 加载时卡在 "loading models"

模型文件是 LFS pointer 没拉下来。`du -sh models/*` 看大小，paraformer-zh 应该接近 2GB。如果只有几 KB，`cd models/paraformer-zh && git lfs pull`。

### 局域网访问 404 / 超时

- WSL 里 `curl http://localhost:8000` 能通 → 服务正常
- Windows PowerShell 里 `curl http://localhost:8000` 能通 → WSL→Windows 转发正常
- 局域网机器不通 → portproxy 或防火墙没设对，参考第 7 节

### 想重置一切

```powershell
wsl --shutdown   # 关掉所有 WSL 实例
# 在 WSL 里：rm -rf funasr/.venv funasr/models
```
