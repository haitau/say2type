#!/bin/zsh

# @raycast.schemaVersion 1
# @raycast.title Say2Type 语音输入
# @raycast.mode silent
# @raycast.packageName say2type
# @raycast.icon 🎙️
# @raycast.description 第一次按开始录音，第二次按结束识别、清洗并粘贴到当前光标

# Raycast 安装方式：
# 1. 打开 Raycast -> Extensions -> Script Commands -> 添加脚本目录，
#    将本 scripts 目录加入；
# 2. 在 Raycast 中为 “Say2Type 语音输入” 分配 Hotkey（建议键盘上单个功能键）；
# 3. 首次运行需授予 Raycast「辅助功能」与「麦克风」权限。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -x ".venv/bin/say2type" ]]; then
  export PATH="$PROJECT_ROOT/.venv/bin:$PATH"
fi

exec say2type once --toggle
