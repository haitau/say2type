# say2type

> macOS 上的纯本地语音输入流水线：**本地 ASR + 本地 LLM 润色 + 光标注入**，
> 面向开发者的中英技术术语混输场景。AI 时代的提交工具。

## 为什么需要它

macOS 原生听写只有声学层、没有语义层：口头禅不去除、技术词被音译成同音字
（“杰森”而不是 `JSON`）、断句机械。现代 AI 语音输入的本质是两段式架构：

```text
[全局热键 / 麦克风采集 (WAV)]
             │
             ▼
[本地 ASR（MLX-Whisper / SenseVoice / 任意 OpenAI 兼容服务）]
             │ 原始口语文本
             ▼
[本地 LLM（Ollama / oMLX，OpenAI 兼容接口）]
   注入开发者 System Prompt：过滤口头禅、修正技术名词、补充标点
             │ 结构化清洗后文本
             ▼
[macOS 注入层（pbcopy + 模拟 Cmd+V，写入当前光标）]
```

全程不联网、数据不出本机。

## 特性

- **ASR 进程内推理，无需起服务**：sherpa-onnx 直接加载本地 SenseVoice-Small ONNX
  （与 voice-record 共享 `~/.voice-record/models` 缓存），模型加载 ~0.4s、
  12.5s 音频推理仅 ~0.1s。
- **LLM 复用常驻 oMLX**：OpenAI 兼容接口 + Bearer Token，按请求指定小模型，
  不影响你 pinned 的 27B 常驻模型。
- **核心零第三方依赖**：除可选的 sherpa-onnx 外仅用标准库
  （`tomllib` / `urllib` / `subprocess` / `wave` / `array`）。
- **热键 toggle 录音**：第一次按开始后台录音，再按一次结束并自动识别、清洗、粘贴，
  状态保存在 `~/.say2type/state.json`，适配 macOS 快捷指令 / Raycast / Logi Options+。
- **ASR / LLM 均可 mock**：没有本地模型时也能联调整条流水线。
- **可迭代的规则系统**：`rules/system_prompt.md` + `rules/custom_vocab.txt`，
  发现新错词直接追加，支持「术语保持」和「错误读法=正确写法」两种词表格式。
- **每次输出耗时统计**：ASR / LLM / 总耗时，方便对照 0.5~1.2s 的体验目标调优。
- 自动备份并恢复剪贴板，不污染用户原有内容；静音输入自动跳过，不会注入标点垃圾。

## 环境要求

- macOS（Apple Silicon 验证通过）+ Python 3.11+（已在 3.15 验证，sherpa-onnx 有 cp315 wheel）
- ffmpeg：`brew install ffmpeg`
- ASR 模型：本地 SenseVoice-Small（sherpa-onnx 格式，voice-record 已缓存）
- LLM：本地 oMLX（或任意 OpenAI 兼容服务，如 Ollama）

## 安装

```bash
git clone <your-repo> say2type && cd say2type

python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[sherpa]'           # sherpa-onnx 有 cp311~cp315 的 macOS arm64 轮子

cp config.example.toml config.toml   # 本地配置，已被 gitignore
say2type devices                     # 查看麦克风序号，填入 config.toml 的 [audio] device
```

### 让任意目录都能直接敲 say2type（推荐）

venv 里的命令默认不在 shell PATH 上。`~/.local/bin` 已在你的 PATH 中，
放一个包装脚本即可全局调用（同时固定配置路径，换目录执行也能读到 API key 与词表）：

```bash
cat > ~/.local/bin/say2type <<'EOF'
#!/bin/zsh
export SAY2TYPE_CONFIG="/Users/shawn/shawn-git/say2type/config.toml"
exec /Users/shawn/shawn-git/say2type/.venv/bin/say2type "$@"
EOF
chmod +x ~/.local/bin/say2type
```

不想加全局命令时，也可以在项目目录里 `source .venv/bin/activate` 后使用，
或始终用 `./scripts/say2type-once.sh`。

### ASR：复用 voice-record 的 SenseVoice 模型

无需启动任何服务，sherpa-onnx 在 say2type 进程内直接读取 ONNX 模型，
默认路径 `~/.voice-record/models/sherpa-onnx-sense-voice-small`
（含 `model.int8.onnx` 232MB + `tokens.txt`）。模型不存在时改 `[asr] sherpa_model_dir`
指向其他 sherpa-onnx 模型目录即可，也可把 `backend` 切成 `"openai"` 对接远程服务。

### LLM：为什么选 oMLX 的 Qwen3-VL-8B 而不是常驻 27B

实测同一清洗任务（本机、27B 常驻占用内存时）：

| 模型 | 冷启动 | 热请求 | 结果 |
| :-- | --: | --: | :-- |
| Qwen3-VL-8B-Instruct-4bit | 3.2s | **0.7s** | 口头禅/术语全部修正，可用 |
| Swift-1.5-Qwen3.8-27b-oQ4e-mtp（常驻） | 12.5s | 8.0s | 听写场景太慢 |
| Ornith-1.5-35B-A3B-MLX-8bit | 加载失败 | — | 需 52.6GB，超出本机动态内存上限 |

因此 `config.toml` 按请求指定 8B 小模型：oMLX 会按需加载，
**不影响 pinned 常驻的 27B**；首次调用有几秒加载开销，之后热请求约 0.7s。
LLM 不是必需组件——把 `[llm] enabled = false` 即可只输出 SenseVoice 原文。
Ollama 用户把 `base_url` 改成 `http://localhost:11434/v1`、清空 `api_key`、
换一个已拉取的模型名即可（这也是需要额外 `ollama pull` 的唯一情形，当前方案不需要）。

### 授予系统权限（两个，缺一不可）

say2type 做的事情是「用 ffmpeg 打开麦克风」+「模拟 Cmd+V 按键」，
macOS 要求宿主程序显式获得这两项权限。**权限绑定的是宿主程序**：
从终端跑就授权终端，从 Raycast/快捷指令跑就授权它们。

1. **麦克风权限** —— 系统设置 → 隐私与安全性 → 麦克风：
   第一次执行 `say2type once` 时系统会自动弹窗，点「允许」即可；
   错过弹窗就到上述设置页手动打开开关。
2. **辅助功能权限** —— 系统设置 → 隐私与安全性 → 辅助功能：
   模拟 Cmd+V 必需。点 `+` 添加宿主程序（Hammerspoon / 终端 / Raycast），
   并确保开关打开。验证命令（有权限时返回进程名而非报错）：

   ```bash
   osascript -e 'tell application "System Events" to get name of first process'
   ```
3. **输入监控权限**（仅双击 Ctrl 热键方案需要）——
   系统设置 → 隐私与安全性 → **输入监控**：把 Hammerspoon 加进去并打开开关。
   这是全局键盘事件监听的独立权限，和「辅助功能」是两个开关，缺一不可；
   授权后需要退出并重新打开 Hammerspoon 才生效。

调试期可以先用 `say2type --print ...` 只打印不注入，此时不需要辅助功能权限。

## 使用

```bash
# 完整流水线：前台录音，回车停止 → ASR → LLM 清洗 → 注入光标
say2type once

# 固定录 3 秒（非 TTY 环境也可用）
say2type once --duration 3

# 热键模式：开始 / 结束  toggle，Raycast 等启动器就调它
say2type once --toggle

# 只录音
say2type record start          # 后台开始
say2type record stop           # 后台结束，打印 wav 路径
say2type record foreground     # 前台交互录音

# 对已有录音做识别（--raw 跳过 LLM）
say2type transcribe /path/to.wav --raw

# 只调试 LLM 清洗效果
say2type clean "呃那个 docker 就是说很方便"

# 无服务联调：ASR/LLM 全部走 mock，不注入只打印
say2type --mock --print once --duration 2
say2type devices
```

标志位放在子命令前后均可：`say2type --mock clean "..."` 与
`say2type clean "..." --mock` 等价。

## 绑定全局热键：双击 Control（推荐方案）

目标手势：在 **tabby / herdr / cc cli 或任何 App** 的光标处，快速双击左/右
Control 开始录音，再双击一次即识别、清洗并把结果粘贴到光标。
macOS 自带的「快捷指令」不支持“双击修饰键”这种触发方式，因此用
[Hammerspoon](https://www.hammerspoon.org/)（开源、本地运行的键盘自动化工具）
做手势识别，配置已内置在 `integrations/hammerspoon/init.lua`。

### 安装（一次性）

```bash
brew install --cask hammerspoon
# 让 ~/.hammerspoon/init.lua 加载仓库中的配置（单一事实来源）
mkdir -p ~/.hammerspoon
cat > ~/.hammerspoon/init.lua <<'EOF'
local ok, err = pcall(dofile, "/Users/shawn/shawn-git/say2type/integrations/hammerspoon/init.lua")
if not ok then hs.alert.show("say2type 配置加载失败：" .. tostring(err), 5) end
EOF
open -a Hammerspoon   # 然后在菜单栏 Hammerspoon 图标里 Reload Config
```

### 授权与自启

1. 系统设置 → 隐私与安全性：给 Hammerspoon 打开 **辅助功能**、**输入监控**、
   **麦克风** 三个开关（见上文「授予系统权限」），授权后重启一次 Hammerspoon；
2. 点菜单栏的 Hammerspoon 图标，勾选 **Launch Hammerspoon at Login**，
   开机后双击 Ctrl 随时可用。

### 手势行为与防误触

- 只统计**纯 Ctrl 点按**：两次点按间隔需在 0.5s 内（对齐 macOS 双击标准），
  超时自动归零；
- Ctrl+C / Ctrl+D / Ctrl+Space 等任何组合键，以及点按之间插入的普通按键，
  都会立即重置计数，终端操作不受影响；
- 录音中菜单栏显示 🔴，并有 `🎙️ 录音中 / ✅ 已输入：…` 的屏幕提示；
- ffmpeg 带 `-t 30` 硬上限，即使停止信号意外丢失也不会无限录音。

### 命令行诊断

```bash
say2type record status        # 查看是否正在录音及对应 PID
hs -c "say2typeDebug()"       # 查看 Hammerspoon 监听器状态与当前计数
hs -c "say2typeTrigger()"     # 跳过手势、直接模拟一次触发
hs -c "hs.reload()"           # 修改 init.lua 后热重载
```

### 备选：普通组合键（不装 Hammerspoon）

若不需要“双击 Ctrl”，可用 macOS 自带「快捷指令」：新建「运行 Shell 脚本」动作，
内容填 `/Users/shawn/.local/bin/say2type once --toggle`，再分配一个普通组合键
（如 `⌃⌥V`）。Raycast / Alfred / Logi Options+ 同理，调用
`scripts/say2type-once.sh` 即可，但这些方式都无法识别双击修饰键手势。

## 规则与词表

- `rules/system_prompt.md`：清洗引擎的 System Prompt，定义输出纪律。
- `rules/custom_vocab.txt`：每行一个术语（要求保持规范写法），
  或 `错误读法=正确写法` 的显式映射，例如：

  ```text
  Docker
  杰森=JSON
  k8s=Kubernetes
  ```

日常使用中发现新的错词，往词表追加即可，无需改代码。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 项目结构

```text
say2type/
├── config.example.toml          # 配置模板（本地 config.toml 不入库）
├── pyproject.toml
├── requirements.txt
├── rules/
│   ├── system_prompt.md         # 语音文本校正 System Prompt
│   └── custom_vocab.txt         # 技术术语与同音纠正词表
├── scripts/
│   ├── raycast-say2type.sh      # Raycast Script Command
│   └── say2type-once.sh         # 通用热键 toggle 包装
├── integrations/
│   └── hammerspoon/init.lua     # 双击 Control 手势识别与状态提示
├── src/say2type/
│   ├── __main__.py              # CLI 入口
│   ├── config.py                # TOML 配置加载（零依赖）
│   ├── pipeline.py              # 端到端编排与耗时统计
│   ├── audio/recorder.py        # ffmpeg 录音 + 后台 toggle 状态
│   ├── asr/client.py            # ASR 分发：sherpa / openai / mock
│   ├── asr/sherpa_backend.py    # sherpa-onnx SenseVoice 进程内推理
│   ├── llm/cleaner.py           # OpenAI 兼容 LLM 清洗 + Prompt 装配
│   └── injector/macos.py        # 剪贴板 + Cmd+V 注入
└── tests/test_smoke.py
```

## 路线图

1. **MVP（当前，已真机验证）**：ffmpeg 录音 → sherpa-onnx SenseVoice
   → oMLX Qwen3-VL-8B 清洗 → pbcopy + 模拟粘贴，端到端约 0.7~0.8s。
2. **按键绑定**：macOS 快捷指令 / Raycast / Logi Options+ 单键触发（脚本已就绪）。
3. **体验迭代**：依据日常错词分布持续扩充 `custom_vocab.txt`；
   后续可选加入 ffmpeg `silencedetect` 静音自动断句（配置项已预留）、
   常驻 sherpa 模型的后台守护模式（省去每次 ~0.4s 模型加载）。
