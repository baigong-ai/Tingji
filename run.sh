#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "需要先安装 ffmpeg (macOS: brew install ffmpeg / Linux: sudo apt install ffmpeg)"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "creating venv..."
  uv venv
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
  echo "警告：LLM_API_KEY 未设置，LLM 整理/总结将不可用"
fi

echo "启动服务，监听 ${HOST}:${PORT}"
if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then
  echo "可访问地址："
  echo "  本机:    http://127.0.0.1:${PORT}"
  if command -v ipconfig >/dev/null 2>&1; then
    for iface in en0 en1 eth0 eth1; do
      ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
      if [ -n "$ip" ]; then
        echo "  局域网:  http://${ip}:${PORT}  (${iface})"
      fi
    done
  elif command -v ip >/dev/null 2>&1; then
    ip -4 addr 2>/dev/null \
      | awk '/inet / && $2 !~ /^127/ {split($2, a, "/"); print a[1]}' \
      | sort -u \
      | while read -r ip; do
          echo "  局域网:  http://${ip}:${PORT}"
        done
  fi
  if command -v hostname >/dev/null 2>&1; then
    echo "  主机名:  http://$(hostname):${PORT}"
  fi
else
  echo "可访问地址: http://${HOST}:${PORT}"
fi
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
