"""macOS 文本注入层。

策略：把待注入文本写入剪贴板，再通过 System Events 模拟 Cmd+V，
注入完成后恢复用户原有剪贴板内容。

首次运行需在「系统设置 -> 隐私与安全性 -> 辅助功能」中为
终端 / Raycast / Alfred 等宿主程序授予辅助功能权限。
"""

from __future__ import annotations

import subprocess
import time

from ..config import InjectorConfig


class InjectionError(RuntimeError):
    """文本注入失败。"""


def _run_osascript(script: str) -> None:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise InjectionError(
            "模拟按键失败（通常是缺少辅助功能权限）。请在「系统设置 -> 隐私与安全性 "
            f"-> 辅助功能」中授权宿主程序。\nosascript 输出：{proc.stderr.strip()}"
        )


def read_clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def write_clipboard(text: str) -> None:
    proc = subprocess.run(["pbcopy"], input=text, text=True)
    if proc.returncode != 0:
        raise InjectionError("写入剪贴板失败（pbcopy）")


def inject_paste(text: str, cfg: InjectorConfig) -> None:
    """将文本粘贴到当前光标位置。"""
    if not text:
        return
    old_clipboard = read_clipboard()
    write_clipboard(text)

    # 等待启动器（Raycast/Alfred）关闭窗口、把焦点交还给目标 App
    time.sleep(cfg.paste_delay)
    _run_osascript('tell application "System Events" to keystroke "v" using command down')

    if cfg.restore_clipboard:
        time.sleep(cfg.restore_delay)
        write_clipboard(old_clipboard)
