#!/bin/bash
# 全量自动化客服质检系统 · macOS 一键构建
# 用法：在这个文件夹里双击本文件（或在终端执行 bash build_macos.command）
# 构建产物 dist/ 里的 .app 已经是独立程序，同事不需要安装 Python。
cd "$(dirname "$0")" || exit 1

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ERROR] 没有找到 python3。"
  echo "        请先在终端执行：xcode-select --install"
  echo "        或安装 python.org 的 Python 3 后再试。"
  exit 1
fi

echo "[BUILD] 使用解释器：$PY"
"$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
if ! "$PY" -c "import PyQt6" >/dev/null 2>&1; then
  echo "[BUILD] 安装依赖（需要联网，约 1-2 分钟）…"
  "$PY" -m pip install -r requirements.txt || { echo "[ERROR] 依赖安装失败"; exit 1; }
fi
if ! "$PY" -m PyInstaller --version >/dev/null 2>&1; then
  echo "[BUILD] 安装 PyInstaller…"
  "$PY" -m pip install pyinstaller || { echo "[ERROR] PyInstaller 安装失败"; exit 1; }
fi

echo "[BUILD] 开始打包 .app（约 2-4 分钟）…"
"$PY" -m PyInstaller --noconfirm --clean --windowed \
  --name "全量自动化客服质检系统" \
  --paths src --collect-submodules qc_engine \
  --exclude-module tkinter app.py
if [ $? -ne 0 ]; then echo "[BUILD] 打包失败"; exit 1; fi

APP="dist/全量自动化客服质检系统.app"
if [ ! -d "$APP" ]; then echo "[BUILD] 未找到 $APP"; exit 1; fi

echo "[COPY] 配置 / 说明书 / 数据目录"
mkdir -p dist/data
rm -rf dist/config dist/docs
cp -R config dist/ 2>/dev/null || true
cp -R docs dist/ 2>/dev/null || true
cp README_给同事.md dist/ 2>/dev/null || true
if [ -f "dist/config/ai_config.json" ]; then rm -f "dist/config/ai_config.json"; fi
if [ -f "config/ai_config.example.json" ]; then cp config/ai_config.example.json "dist/config/ai_config.json"; fi
chmod +x "$APP/Contents/MacOS/全量自动化客服质检系统" 2>/dev/null || true
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

ZIP="全量自动化客服质检系统_macOS.zip"
rm -f "$ZIP"
if command -v ditto >/dev/null 2>&1; then
  ditto -c -k --sequesterRsrc --keepParent dist "$ZIP"
else
  (cd dist && zip -r "../$ZIP" .)
fi

echo ""
echo "[DONE] 已生成：dist/全量自动化客服质检系统.app"
echo "[ZIP ] 已生成：$ZIP"
echo "       把 zip 解压后整个文件夹发给同事；macOS 用户双击 .app 即可使用（不需要装 Python）。"
echo "       如果首次打开提示“无法验证开发者”，右键点 .app 选“打开”，或执行："
echo "       xattr -dr com.apple.quarantine 全量自动化客服质检系统.app"
