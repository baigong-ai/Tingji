#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

PID_FILE="logs/tingji.pid"
LOG_FILE="logs/tingji.out"

usage() {
  cat <<EOF
用法:
  ./run.sh              前台运行（默认）
  ./run.sh -d|--daemon  后台运行（脱离终端，PID 写入 ${PID_FILE}，输出写入 ${LOG_FILE}）
  ./run.sh --stop       停止后台进程
  ./run.sh --status     查看后台进程状态
  ./run.sh -h|--help    显示本帮助
EOF
}

ACTION="foreground"
case "${1:-}" in
  -d|--daemon) ACTION="daemon" ;;
  --stop)      ACTION="stop" ;;
  --status)    ACTION="status" ;;
  -h|--help)   usage; exit 0 ;;
  "")          ;;
  *) echo "未知参数: $1"; usage; exit 1 ;;
esac

read_running_pid() {
  [ -f "$PID_FILE" ] || { echo ""; return; }
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "$pid"
  else
    echo ""
  fi
}

if [ "$ACTION" = "status" ]; then
  pid="$(read_running_pid)"
  if [ -n "$pid" ]; then
    echo "运行中: PID ${pid}（日志: ${LOG_FILE}）"
    exit 0
  fi
  echo "未运行"
  exit 0
fi

if [ "$ACTION" = "stop" ]; then
  pid="$(read_running_pid)"
  if [ -z "$pid" ]; then
    echo "未运行（或 $PID_FILE 已失效）"
    rm -f "$PID_FILE"
    exit 0
  fi
  echo "停止 PID $pid ..."
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.3
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "未在 3s 内退出，发送 SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "已停止"
  exit 0
fi

# foreground or daemon — both need the env setup below
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

# Read nested server.ssl config via Python so we don't need yq.
SSL_INFO=$(.venv/bin/python -c "
from app.config import load_config
try:
    cfg = load_config('config.yaml')
    s = cfg.server.ssl
    print(f'{int(s.enabled)}|{s.cert}|{s.key}|{int(s.auto_generate)}')
except Exception:
    print('0|certs/cert.pem|certs/key.pem|1')
" 2>/dev/null || echo "0|certs/cert.pem|certs/key.pem|1")
IFS='|' read -r SSL_ENABLED SSL_CERT SSL_KEY SSL_AUTO_GEN <<< "$SSL_INFO"

SSL_ARGS=""
SCHEME="http"
if [ "$SSL_ENABLED" = "1" ]; then
  if [ "$SSL_AUTO_GEN" = "1" ] && { [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; }; then
    echo "首次启用 HTTPS，自动生成自签名证书到 $(dirname "$SSL_CERT")..."
    mkdir -p "$(dirname "$SSL_CERT")"
    if ! openssl req -x509 -newkey rsa:2048 -keyout "$SSL_KEY" -out "$SSL_CERT" -days 365 -nodes -subj "/CN=tingji.local" >/dev/null 2>&1; then
      echo "错误：无法生成自签名证书，请确认系统已安装 openssl"
      exit 1
    fi
  fi
  if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
    echo "错误：SSL 证书或私钥不存在：cert=$SSL_CERT key=$SSL_KEY"
    exit 1
  fi
  SSL_ARGS="--ssl-keyfile $SSL_KEY --ssl-certfile $SSL_CERT"
  SCHEME="https"
fi

if grep -q 'mode: api' config.yaml && [ -z "${LLM_API_KEY:-}" ]; then
  echo "警告：LLM_API_KEY 未设置，LLM 整理/总结将不可用"
fi

# Refuse to start a second daemon if one is already running.
pid="$(read_running_pid)"
if [ -n "$pid" ]; then
  echo "已有后台进程在运行: PID ${pid}（先 ./run.sh --stop 再启动）"
  exit 1
fi

print_urls() {
  if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then
    echo "可访问地址："
    echo "  本机:    ${SCHEME}://127.0.0.1:${PORT}"
    if command -v ipconfig >/dev/null 2>&1; then
      for iface in en0 en1 eth0 eth1; do
        ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
        if [ -n "$ip" ]; then
          echo "  局域网:  ${SCHEME}://${ip}:${PORT}  (${iface})"
        fi
      done
    elif command -v ip >/dev/null 2>&1; then
      ip -4 addr 2>/dev/null \
        | awk '/inet / && $2 !~ /^127/ {split($2, a, "/"); print a[1]}' \
        | sort -u \
        | while read -r ip; do
            echo "  局域网:  ${SCHEME}://${ip}:${PORT}"
          done
    fi
    if command -v hostname >/dev/null 2>&1; then
      echo "  主机名:  ${SCHEME}://$(hostname):${PORT}"
    fi
  else
    echo "可访问地址: ${SCHEME}://${HOST}:${PORT}"
  fi
}

if [ "$ACTION" = "daemon" ]; then
  mkdir -p logs
  echo "后台启动服务，监听 ${HOST}:${PORT}（PID → ${PID_FILE}，日志 → ${LOG_FILE}）"
  # nohup + disown: SIGHUP ignored, survives terminal close. (setsid is not
  # in stock macOS, nohup is.)
  nohup .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" $SSL_ARGS \
    >"$LOG_FILE" 2>&1 < /dev/null &
  DAEMON_PID=$!
  echo "$DAEMON_PID" > "$PID_FILE"
  disown 2>/dev/null || true
  sleep 1
  if kill -0 "$DAEMON_PID" 2>/dev/null; then
    echo "已启动: PID ${DAEMON_PID}"
    print_urls
  else
    echo "启动失败，最近日志:"
    tail -20 "$LOG_FILE" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
  fi
  exit 0
fi

echo "启动服务，监听 ${HOST}:${PORT}"
print_urls
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" $SSL_ARGS
