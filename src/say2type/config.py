"""配置加载：默认使用标准库 tomllib 读取 TOML，零第三方依赖。

若安装了 PyYAML，也支持 config.yaml；查找顺序见 ``find_config_path``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+ 标准库
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

CONFIG_DIR = Path.home() / ".say2type"
STATE_FILE = CONFIG_DIR / "state.json"

# 配置文件候选（优先级从高到低）
CONFIG_CANDIDATES = [
    "config.toml",
    "config.yaml",
    "config.yml",
    str(Path.home() / ".config" / "say2type" / "config.toml"),
]


@dataclass
class AudioConfig:
    # avfoundation 设备序号，通过 `say2type devices` 查看；null 表示系统默认输入
    device: int | None = None
    sample_rate: int = 16000
    channels: int = 1
    # 单次录音硬上限（秒），防止忘记停止
    max_duration: float = 30.0
    # 检测到持续静音后自动停止（基于 ffmpeg silencedetect）
    silence_stop: bool = False
    silence_db: float = -40.0
    silence_seconds: float = 2.0
    # 录音文件输出目录，空字符串表示临时目录
    output_dir: str = ""


@dataclass
class AsrConfig:
    enabled: bool = True
    # sherpa: 进程内 sherpa-onnx（默认，复用本地 ONNX 模型）
    # openai: OpenAI 兼容的 /v1/audio/transcriptions 接口；mock: 离线假数据
    backend: str = "sherpa"
    base_url: str = "http://localhost:8000/v1"
    api_key: str = ""
    model: str = "whisper-1"
    # zh / en / 留空 "" 让模型自动判别
    language: str = "zh"
    timeout: float = 60.0
    # 传给 ASR 的初始 prompt（帮助识别专有名词），可留空
    extra_prompt: str = ""
    # ---- sherpa 后端专用 ----
    # 与 voice-record 共享的 SenseVoice-Small 模型目录
    sherpa_model_dir: str = "~/.voice-record/models/sherpa-onnx-sense-voice-small"
    sherpa_num_threads: int = 4
    # ITN: 逆文本正则化，把“二零二四年”转成“2024 年”等
    sherpa_use_itn: bool = True


@dataclass
class LlmConfig:
    enabled: bool = True
    # openai: OpenAI 兼容的 /v1/chat/completions（Ollama / oMLX 均兼容）；mock: 原样返回
    backend: str = "openai"
    base_url: str = "http://127.0.0.1:8000/v1"
    # oMLX 等需要 Bearer Token 的服务填这里；Ollama 留空即可
    api_key: str = ""
    model: str = "Qwen3-VL-8B-Instruct-4bit"
    timeout: float = 60.0
    temperature: float = 0.1
    max_tokens: int = 1024


@dataclass
class InjectorConfig:
    # true: 模拟 Cmd+V 注入当前光标；false: 仅打印到标准输出
    enabled: bool = True
    # 注入前等待，给 Raycast/Alfred 等启动器留出关闭窗口、交还焦点的时间
    paste_delay: float = 0.15
    # 注入后恢复原有剪贴板内容
    restore_clipboard: bool = True
    restore_delay: float = 0.3


@dataclass
class RulesConfig:
    # 相对于配置文件所在目录解析
    system_prompt: str = "rules/system_prompt.md"
    custom_vocab: str = "rules/custom_vocab.txt"


@dataclass
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    injector: InjectorConfig = field(default_factory=InjectorConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    # 记录配置文件位置，供相对路径解析；不参与序列化合并
    config_path: str = field(default="", repr=False)


def _merge(section: Any, payload: dict[str, Any]) -> Any:
    """将 dict 按字段名合并进 dataclass 实例，忽略未知键。"""
    if not is_dataclass(section) or not isinstance(payload, dict):
        return section
    known = {f.name for f in fields(section)}
    for key, value in payload.items():
        if key in known:
            setattr(section, key, value)
    return section


def _parse_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("当前 Python 缺少 tomllib，请升级到 3.11+ 或改用 config.yaml")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _parse_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"检测到 YAML 配置 {path}，但未安装 PyYAML；请 pip install PyYAML 或改用 config.toml"
        ) from exc
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def find_config_path(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"指定的配置文件不存在: {path}")
        return path
    env_path = os.environ.get("SAY2TYPE_CONFIG")
    if env_path:
        path = Path(env_path).expanduser()
        if path.exists():
            return path
    for candidate in CONFIG_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def load_config(explicit: str | os.PathLike[str] | None = None) -> AppConfig:
    """加载配置；找不到任何配置文件时返回内置默认值。"""
    cfg = AppConfig()
    path = find_config_path(explicit)
    if path is None:
        return cfg

    if path.suffix in {".yaml", ".yml"}:
        data = _parse_yaml(path)
    else:
        data = _parse_toml(path)

    _merge(cfg.audio, data.get("audio", {}))
    _merge(cfg.asr, data.get("asr", {}))
    _merge(cfg.llm, data.get("llm", {}))
    _merge(cfg.injector, data.get("injector", {}))
    _merge(cfg.rules, data.get("rules", {}))
    cfg.config_path = str(path.resolve())
    return cfg


def project_root(cfg: AppConfig) -> Path:
    """配置文件所在目录即项目根目录；无配置文件时退回当前工作目录。"""
    if cfg.config_path:
        return Path(cfg.config_path).parent
    return Path.cwd()


def resolve_rule_path(cfg: AppConfig, relative: str) -> Path:
    path = Path(relative).expanduser()
    if path.is_absolute():
        return path
    return project_root(cfg) / path
