"""基于 ffmpeg + avfoundation 的 macOS 录音模块。

两种工作模式：

* 前台交互模式 :meth:`Recorder.record_interactive` —— 回车停止，
  支持最长时长兜底与静音自动停止，适合终端调试。
* 后台 toggle 模式 :meth:`start_background` / :meth:`stop_background` ——
  ffmpeg 脱离终端运行，状态写入 ``~/.say2type/state.json``，
  供 Raycast / Alfred / 罗技按键每次热键切换“开始/结束”。
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import CONFIG_DIR, STATE_FILE, AudioConfig

_DEVICE_RE = re.compile(r"\[(\d+)\]\s*(.+?)\s*$")
_SILENCE_RE = re.compile(r"silence_start:\s*([\d.]+)")


class AudioDeviceError(RuntimeError):
    """音频设备或 ffmpeg 相关错误。"""


@dataclass
class BackgroundState:
    pid: int
    wav_path: str
    log_path: str
    started_at: float

    @classmethod
    def load(cls) -> "BackgroundState | None":
        if not STATE_FILE.exists():
            return None
        try:
            return cls(**json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return None

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")

    def clear(self) -> None:
        STATE_FILE.unlink(missing_ok=True)

    def alive(self) -> bool:
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:  # pragma: no cover
            return True
        return True


def _require_ffmpeg() -> str:
    try:
        return subprocess.check_output(["which", "ffmpeg"], text=True).strip()
    except subprocess.CalledProcessError as exc:
        raise AudioDeviceError(
            "未找到 ffmpeg，请先安装：brew install ffmpeg"
        ) from exc


def list_devices() -> list[tuple[int, str]]:
    """枚举 avfoundation 音频输入设备，返回 [(序号, 名称), ...]。"""
    _require_ffmpeg()
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    # 设备清单打印在 stderr；音频段落在 "AVFoundation audio devices:" 之后
    lines = proc.stderr.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if "AVFoundation audio devices" in line)
    except StopIteration:
        return []
    devices: list[tuple[int, str]] = []
    for line in lines[start + 1 :]:
        match = _DEVICE_RE.search(line)
        if match:
            devices.append((int(match.group(1)), match.group(2).strip()))
        elif devices and line.strip():
            # 音频段之后遇到非设备行即结束
            break
    return devices


class Recorder:
    def __init__(self, cfg: AudioConfig) -> None:
        self.cfg = cfg
        self.ffmpeg = _require_ffmpeg()

    # ------------------------------------------------------------------ #
    # 命令构造
    # ------------------------------------------------------------------ #
    def _output_path(self) -> Path:
        if self.cfg.output_dir:
            out_dir = Path(self.cfg.output_dir).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="say2type-"))
        return out_dir / f"rec-{int(time.time())}.wav"

    def _ffmpeg_cmd(self, wav_path: Path) -> list[str]:
        # avfoundation 输入格式 "[视频]:[音频]"，":N" 表示仅音频设备 N；
        # 设备为 None 时用 ":" 走系统默认输入。
        device_spec = ":" if self.cfg.device is None else f":{self.cfg.device}"
        cmd = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "info",
            "-y",
            "-f",
            "avfoundation",
            "-i",
            device_spec,
            "-ar",
            str(self.cfg.sample_rate),
            "-ac",
            str(self.cfg.channels),
        ]
        if self.cfg.silence_stop:
            cmd += [
                "-af",
                f"silencedetect=n={self.cfg.silence_db}dB:d={self.cfg.silence_seconds}",
            ]
        # 硬性时长上限：即使停止信号丢失（状态文件被误删等），ffmpeg 也会自动退出，
        # 杜绝后台无限录音
        cmd += ["-t", str(self.cfg.max_duration)]
        cmd += ["-c:a", "pcm_s16le", str(wav_path)]
        return cmd

    @staticmethod
    def _graceful_stop(proc: subprocess.Popen[str]) -> None:
        """优先向 ffmpeg stdin 发送 q 优雅收尾，失败再终止进程。"""
        if proc.poll() is not None:
            return
        try:
            assert proc.stdin is not None
            proc.stdin.write("q")
            proc.stdin.flush()
            proc.wait(timeout=5)
        except (BrokenPipeError, OSError):
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ------------------------------------------------------------------ #
    # 前台交互模式
    # ------------------------------------------------------------------ #
    def record_interactive(self) -> Path:
        """录制直到回车 / 达到最长时长 / 触发静音自动停止。"""
        wav_path = self._output_path()
        cmd = self._ffmpeg_cmd(wav_path)
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stop_event = threading.Event()

        def _watch_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                if self.cfg.silence_stop and _SILENCE_RE.search(line):
                    sys.stderr.write("\n[say2type] 检测到静音，自动停止录音\n")
                    stop_event.set()

        reader = threading.Thread(target=_watch_stderr, daemon=True)
        reader.start()

        def _max_duration() -> None:
            if stop_event.wait(timeout=self.cfg.max_duration):
                return
            sys.stderr.write("\n[say2type] 达到最长录音时长，自动停止\n")
            stop_event.set()

        timer = threading.Thread(target=_max_duration, daemon=True)
        timer.start()

        if sys.stdin.isatty():
            input("按回车停止录音…\n")
            stop_event.set()
        else:
            # 无 TTY（被脚本调用）时由时长 / 静音决定停止
            stop_event.wait()

        self._graceful_stop(proc)
        reader.join(timeout=2)
        if not wav_path.exists() or wav_path.stat().st_size == 0:
            raise AudioDeviceError(
                f"录音失败，请检查设备序号 {self.cfg.device!r}（执行 say2type devices 查看）"
            )
        return wav_path

    # ------------------------------------------------------------------ #
    # 后台 toggle 模式（热键开始 / 再按结束）
    # ------------------------------------------------------------------ #
    def start_background(self) -> BackgroundState:
        existing = BackgroundState.load()
        if existing and existing.alive():
            raise AudioDeviceError("已有录音正在进行，再按一次热键即可结束")

        wav_path = self._output_path()
        log_path = wav_path.with_suffix(".log")
        log_fh = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            self._ffmpeg_cmd(wav_path),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # 给 ffmpeg 一点时间打开设备，立刻失败时能给出明确报错
        time.sleep(0.4)
        if proc.poll() is not None:
            log_fh.close()
            detail = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            raise AudioDeviceError(
                f"ffmpeg 启动失败（退出码 {proc.returncode}），检查设备序号。日志：\n{detail}"
            )
        state = BackgroundState(
            pid=proc.pid,
            wav_path=str(wav_path),
            log_path=str(log_path),
            started_at=time.time(),
        )
        state.save()
        return state

    @staticmethod
    def stop_background() -> Path:
        """向后台 ffmpeg 发送 SIGINT 优雅结束，返回 wav 路径。"""
        state = BackgroundState.load()
        if state is None:
            raise AudioDeviceError("没有进行中的录音（状态文件不存在）")
        if state.alive():
            # ffmpeg 对 SIGINT 做了优雅退出处理，会正确收尾 WAV 文件头
            os.kill(state.pid, signal.SIGINT)
            deadline = time.time() + 8
            while time.time() < deadline:
                if not state.alive():
                    break
                time.sleep(0.1)
            else:
                os.kill(state.pid, signal.SIGKILL)
        state.clear()
        wav_path = Path(state.wav_path)
        if not wav_path.exists() or wav_path.stat().st_size == 0:
            raise AudioDeviceError(f"录音文件无效：{wav_path}")
        return wav_path
