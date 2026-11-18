#!/bin/bash
# 从源码启动（开发/临时用；发给同事请用 build_macos.command 生成独立 .app）
cd "$(dirname "$0")" || exit 1
PY="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ERROR] 没有找到 python3，请先安装（或运行 build_macos.command 生成独立 .app）。"
  exit 1
fi
if ! "$PY" -c "import PyQt6" >/dev/null 2>&1; then
  echo "[INFO] 首次运行，安装依赖…"
  "$PY" -m pip install -r requirements.txt || exit 1
fi
exec "$PY" app.py
