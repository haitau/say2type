"""say2type 命令行入口。

子命令：
  once       录音 -> 识别 -> 清洗 -> 注入（默认子命令，可省略）
  record     仅录音（start/stop 后台 toggle，或前台交互）
  transcribe 对已有 WAV 做 ASR（可选再清洗）
  clean      直接清洗一段文本，用于调试 LLM
  devices    列出 avfoundation 音频输入设备
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .asr.client import AsrClient
from .audio.recorder import AudioDeviceError, Recorder, list_devices
from .config import AppConfig, load_config
from .llm.cleaner import LlmCleaner, build_system_prompt
from .pipeline import process_wav, report_timing


def _build_parser() -> argparse.ArgumentParser:
    # 公共参数同时挂到主 parser 与各子 parser，使标志位放在子命令前后都能识别；
    # 子 parser 使用 SUPPRESS 默认值，避免覆盖主 parser 已解析出的值。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="配置文件路径（默认查找 ./config.toml）",
                        default=argparse.SUPPRESS)
    common.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        default=argparse.SUPPRESS,
        help="只打印结果，不模拟 Cmd+V 注入",
    )
    common.add_argument("--mock", action="store_true", default=argparse.SUPPRESS,
                        help="ASR/LLM 全部使用 mock 后端联调")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
                        help="输出调试信息")

    parser = argparse.ArgumentParser(
        prog="say2type",
        parents=[common],
        description="macOS 纯本地语音输入：本地 ASR + 本地 LLM 清洗 + 光标注入",
    )
    parser.add_argument("--version", action="version", version=f"say2type {__version__}")
    # 注意：不要用 parser.set_defaults() 给这些 dest 设默认值——Python 3.15 的
    # argparse 会因此改写共享 action 的 SUPPRESS 默认值，使子 parser 覆盖主 parser
    # 已解析的全局参数。缺失属性在 main() 中用 getattr 归一化。

    sub = parser.add_subparsers(dest="command")

    p_once = sub.add_parser("once", parents=[common], help="完整跑一遍流水线（默认子命令）")
    p_once.add_argument(
        "--toggle",
        action="store_true",
        help="热键模式：第一次调用后台开始录音，第二次调用结束并走完整流水线",
    )
    p_once.add_argument("--duration", type=float, help="前台模式固定录音秒数")
    p_once.set_defaults(func=cmd_once)

    p_record = sub.add_parser("record", parents=[common], help="仅录音，产出 WAV 文件")
    p_record.add_argument("action", choices=["start", "stop", "foreground"], nargs="?",
                          default="foreground")
    p_record.add_argument("--duration", type=float, help="前台固定录音秒数")
    p_record.set_defaults(func=cmd_record)

    p_trans = sub.add_parser("transcribe", parents=[common],
                             help="对 WAV 文件执行 ASR（可选 LLM 清洗）")
    p_trans.add_argument("wav", type=Path)
    p_trans.add_argument("--raw", action="store_true", help="只输出 ASR 原文，跳过 LLM")
    p_trans.set_defaults(func=cmd_transcribe)

    p_clean = sub.add_parser("clean", parents=[common], help="对给定文本执行 LLM 清洗")
    p_clean.add_argument("text", nargs="?", help="待清洗文本；省略则从 stdin 读取")
    p_clean.set_defaults(func=cmd_clean)

    sub.add_parser("devices", parents=[common],
                   help="列出音频输入设备").set_defaults(func=cmd_devices)
    return parser


def _apply_flags(cfg: AppConfig, args: argparse.Namespace) -> AppConfig:
    if getattr(args, "mock", False):
        cfg.asr.backend = "mock"
        cfg.llm.backend = "mock"
    if getattr(args, "print_only", False):
        cfg.injector.enabled = False
    return cfg


def cmd_devices(cfg: AppConfig, args: argparse.Namespace) -> int:
    for index, name in list_devices():
        marker = " *" if cfg.audio.device == index else ""
        print(f"[{index}] {name}{marker}")
    print("\n* = 当前配置选中的设备；在 config.toml 的 [audio] device 中修改")
    return 0


def cmd_once(cfg: AppConfig, args: argparse.Namespace) -> int:
    recorder = Recorder(cfg.audio)

    if args.toggle:
        from .audio.recorder import BackgroundState

        state = BackgroundState.load()
        if state and state.alive():
            wav_path = Recorder.stop_background()
            sys.stderr.write(f"[say2type] 录音结束：{wav_path}\n")
        else:
            state = recorder.start_background()
            sys.stderr.write(f"[say2type] 开始后台录音（再次执行以结束）：{state.wav_path}\n")
            return 0
    else:
        if args.duration:
            cfg.audio.max_duration = args.duration
            cfg.audio.silence_stop = False
        wav_path = recorder.record_interactive()

    result = process_wav(wav_path, cfg, inject=cfg.injector.enabled)
    report_timing(result, injected=cfg.injector.enabled)
    if not cfg.injector.enabled:
        print(result.final_text)
    return 0


def cmd_record(cfg: AppConfig, args: argparse.Namespace) -> int:
    recorder = Recorder(cfg.audio)
    if args.action == "start":
        state = recorder.start_background()
        print(state.wav_path)
    elif args.action == "stop":
        print(Recorder.stop_background())
    else:
        if args.duration:
            cfg.audio.max_duration = args.duration
            cfg.audio.silence_stop = False
        print(recorder.record_interactive())
    return 0


def cmd_transcribe(cfg: AppConfig, args: argparse.Namespace) -> int:
    raw = AsrClient(cfg.asr).transcribe(args.wav)
    if args.raw or not cfg.llm.enabled:
        print(raw)
        return 0
    final = LlmCleaner(cfg.llm, build_system_prompt(cfg)).clean(raw)
    print(final)
    return 0


def cmd_clean(cfg: AppConfig, args: argparse.Namespace) -> int:
    text = args.text if args.text else sys.stdin.read()
    print(LlmCleaner(cfg.llm, build_system_prompt(cfg)).clean(text))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # 无子命令时默认 once
    raw_args = sys.argv[1:] if argv is None else argv
    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in {
        "once", "record", "transcribe", "clean", "devices"
    }:
        raw_args = ["once", *raw_args]
    args = parser.parse_args(raw_args)
    if not getattr(args, "command", None):
        args = parser.parse_args([*(raw_args or []), "once"])

    # 公共参数使用 SUPPRESS 默认值，未提供时属性不存在，这里统一补齐
    for name, default in (
        ("mock", False),
        ("print_only", False),
        ("verbose", False),
        ("config", None),
    ):
        if not hasattr(args, name):
            setattr(args, name, default)

    cfg = _apply_flags(load_config(args.config), args)
    try:
        return args.func(cfg, args)
    except Exception as exc:  # noqa: BLE001 - CLI 统一兜底
        if args.verbose:
            raise
        sys.stderr.write(f"[say2type] 错误: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
