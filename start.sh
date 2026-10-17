#!/usr/bin/env bash
# 用你的声音读睡前故事 —— macOS / Linux 启动脚本
# 用法： ./start.sh [--check] [--install] [--all] [--project 我的故事]
set -e
cd "$(dirname "$0")"

for c in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    exec "$c" app.py "$@"
  fi
done

echo "找不到 python3。请先装 Python 3.10 以上。"
exit 1
