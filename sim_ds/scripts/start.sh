#!/usr/bin/env bash
# One-click development startup: backend API + Vite frontend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RUN_DIR="$ROOT/.run"
LOG_DIR="$ROOT/logs/dev"
BACKEND_PID="$RUN_DIR/backend.pid"
FRONTEND_PID="$RUN_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

mkdir -p "$RUN_DIR" "$LOG_DIR"
cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "缺少 Python 虚拟环境：$PYTHON_BIN" >&2
  echo "请先执行：python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

alive() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

port_busy() {
  local port="$1"
  "$PYTHON_BIN" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
sock.settimeout(0.4)
sys.exit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

wait_http() {
  local url="$1"
  local name="$2"
  local log="$3"
  for _ in $(seq 1 40); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "$name 启动失败，日志末尾：" >&2
  tail -n 30 "$log" >&2 || true
  return 1
}

if alive "$BACKEND_PID"; then
  echo "后端已在运行 (PID $(cat "$BACKEND_PID"))"
elif port_busy "$BACKEND_PORT"; then
  echo "端口 $BACKEND_PORT 已被占用，先执行 ./scripts/stop.sh 或设置 BACKEND_PORT" >&2
  exit 1
else
  : >"$BACKEND_LOG"
  nohup env PYTHONPATH="$ROOT" "$PYTHON_BIN" -m uvicorn backend.main:app \
    --host 0.0.0.0 --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID"
  wait_http "http://127.0.0.1:$BACKEND_PORT/api/health" "后端" "$BACKEND_LOG"
  echo "后端已启动 (PID $(cat "$BACKEND_PID"))"
fi

if [[ ! -d "$ROOT/frontend/app/node_modules" ]]; then
  echo "安装前端依赖..."
  (cd "$ROOT/frontend/app" && npm install --no-audit --no-fund)
fi

if alive "$FRONTEND_PID"; then
  echo "前端已在运行 (PID $(cat "$FRONTEND_PID"))"
elif port_busy "$FRONTEND_PORT"; then
  echo "端口 $FRONTEND_PORT 已被占用，先执行 ./scripts/stop.sh 或设置 FRONTEND_PORT" >&2
  exit 1
else
  : >"$FRONTEND_LOG"
  (
    cd "$ROOT/frontend/app"
    nohup env VITE_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" \
      ./node_modules/.bin/vite --host 0.0.0.0 --port "$FRONTEND_PORT" \
      >"$FRONTEND_LOG" 2>&1 &
    echo $! >"$FRONTEND_PID"
  )
  wait_http "http://127.0.0.1:$FRONTEND_PORT/" "前端" "$FRONTEND_LOG"
  echo "前端已启动 (PID $(cat "$FRONTEND_PID"))"
fi

echo
echo "后端 API : http://localhost:$BACKEND_PORT"
echo "API 文档 : http://localhost:$BACKEND_PORT/docs"
echo "前端页面 : http://localhost:$FRONTEND_PORT"
echo "后端日志 : $BACKEND_LOG"
echo "前端日志 : $FRONTEND_LOG"
echo "停止服务 : ./scripts/stop.sh"
