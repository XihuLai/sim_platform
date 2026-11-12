#!/usr/bin/env bash
# Stop services started by scripts/start.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"

stop_one() {
  local name="$1"
  local pid_file="$RUN_DIR/$2.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name 未运行（无 PID 文件）"
    return
  fi
  local pid
  pid="$(cat "$pid_file")"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name 未运行（PID $pid 已退出）"
    rm -f "$pid_file"
    return
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "$name 已停止 (PID $pid)"
      return
    fi
    sleep 0.25
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  echo "$name 已强制停止 (PID $pid)"
}

stop_one "前端" frontend
stop_one "后端" backend
