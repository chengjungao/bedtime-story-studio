#!/usr/bin/env bash
# 一键环境：先查，缺什么装什么，装完再查一遍。
# 用法： ./setup.sh            （会问一句要不要装）
#        ./setup.sh --yes      （不问，直接装）
#        ./setup.sh --cpu      （没有 N 卡时装 CPU 版 PyTorch）
set -e
cd "$(dirname "$0")"

for c in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    exec "$c" app.py --setup "$@"
  fi
done

echo "找不到 python3。请先装 Python 3.10 以上。"
exit 1
