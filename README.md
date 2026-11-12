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

- **零第三方 Python 运行时依赖**：仅用标准库（`tomllib` / `urllib` / `subprocess`），
  音频采集依赖系统级 `ffmpeg`，不会卡在 Python 3.15 的 wheel 适配上。
- **热键 toggle 录音**：第一次按开始后台录音，再按一次结束并自动识别、清洗、粘贴，
  状态保存在 `~/.say2type/state.json`，天然适配 Raycast / Alfred / Logi Options+。
- **ASR / LLM 均可 mock**：没有本地服务时也能联调整条流水线。
- **可迭代的规则系统**：`rules/system_prompt.md` + `rules/custom_vocab.txt`，
  发现新错词直接追加，支持「术语保持」和「错误读法=正确写法」两种词表格式。
- **每次输出耗时统计**：ASR / LLM / 总耗时，方便对照 0.5~1.2s 的体验目标调优。
- 自动备份并恢复剪贴板，不污染用户原有内容。

## 环境要求

- macOS（Apple Silicon 验证通过）+ Python 3.11+
- ffmpeg：`brew install ffmpeg`
- 一个 OpenAI 兼容的本地 ASR 服务（`/v1/audio/transcriptions`）
- 一个 OpenAI 兼容的本地 LLM 服务（Ollama 或 oMLX 的 `/v1/chat/completions`）

## 安装

```bash
git clone <your-repo> say2type && cd say2type

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp config.example.toml config.toml   # 本地配置，已被 gitignore
say2type devices                     # 查看麦克风序号，填入 config.toml 的 [audio] device
```

### 准备 LLM（Ollama 示例）

```bash
ollama pull qwen2.5:7b      # 7B 量级在 M 系列上延迟与效果较均衡
```

Ollama 默认监听 `http://localhost:11434/v1`，已与 `config.example.toml` 对齐。
oMLX 用户把 `[llm] base_url` / `model` 换成对应端点即可，协议同样是 OpenAI 兼容。

### 准备 ASR

任何暴露 OpenAI `/v1/audio/transcriptions` 的本地服务均可，例如
faster-whisper-server、mlx-omni-server 等。启动后把地址写入 `config.toml`：

```toml
[asr]
backend = "openai"
base_url = "http://localhost:8000/v1"
model = "whisper-1"      # 以具体服务支持的模型名为准
language = "zh"
```

### 授予系统权限

首次运行需要给宿主程序（终端 / Raycast / Alfred）授权：

1. **系统设置 → 隐私与安全性 → 麦克风**
2. **系统设置 → 隐私与安全性 → 辅助功能**（模拟 Cmd+V 必需）

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

## 绑定全局热键

### Raycast（推荐）

1. Raycast → Extensions → Script Commands，把本项目 `scripts/` 目录加入；
2. 为 **Say2Type 语音输入**（`scripts/raycast-say2type.sh`）分配 Hotkey；
3. 按一下开始说话，再按一下自动识别并粘贴到当前光标。

### Logi Options+（罗技键盘）

把任意功能键映射为「打开应用/文件」，指向
`scripts/say2type-once.sh`；或映射为 Raycast 的上述 Hotkey。

### Alfred

在 Workflow 的 Run Script / Terminal Command 中执行
`/path/to/say2type/scripts/say2type-once.sh`。

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
├── src/say2type/
│   ├── __main__.py              # CLI 入口
│   ├── config.py                # TOML 配置加载（零依赖）
│   ├── pipeline.py              # 端到端编排与耗时统计
│   ├── audio/recorder.py        # ffmpeg 录音 + 后台 toggle 状态
│   ├── asr/client.py            # OpenAI 兼容 ASR 客户端
│   ├── llm/cleaner.py           # OpenAI 兼容 LLM 清洗 + Prompt 装配
│   └── injector/macos.py        # 剪贴板 + Cmd+V 注入
└── tests/test_smoke.py
```

## 路线图

1. **MVP（当前）**：录音 → 本地 ASR → Ollama/oMLX → pbcopy + 模拟粘贴闭环，
   用 mock 后端即可完整联调。
2. **按键绑定**：Raycast / Logi Options+ 单键触发（脚本已就绪）。
3. **体验迭代**：依据日常错词分布持续扩充 `custom_vocab.txt`；
   后续可选加入 ffmpeg `silencedetect` 静音自动断句（配置项已预留）。
