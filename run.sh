#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "需要先安装 ffmpeg: brew install ffmpeg"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "creating venv..."
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
  echo "警告：LLM_API_KEY 未设置，LLM 整理/总结将不可用"
fi

echo "启动: http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
