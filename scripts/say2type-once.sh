#!/bin/zsh
# 通用热键包装：每次执行在“开始录音 / 结束并注入”之间切换。
# 可被 Raycast Script Command、Alfred Workflow(nsaction)、Logi Options+ 调用。

set -euo pipefail

# 解析项目根目录（本脚本位于 scripts/ 下）
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 优先使用项目内虚拟环境
if [[ -x ".venv/bin/say2type" ]]; then
  export PATH="$PROJECT_ROOT/.venv/bin:$PATH"
fi

exec say2type once --toggle "$@"
