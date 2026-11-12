"""say2type —— macOS 纯本地语音输入流水线。

数据流：麦克风采集 (ffmpeg) -> 本地 ASR -> 本地 LLM 清洗 -> 模拟 Cmd+V 注入。
"""

__version__ = "0.1.0"
