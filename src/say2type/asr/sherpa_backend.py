"""sherpa-onnx 进程内 ASR 后端，直接复用本地 ONNX 模型缓存。

默认加载 SenseVoice-Small（与 voice-record 共享
``~/.voice-record/models/sherpa-onnx-sense-voice-small``），
无需启动任何额外服务。依赖通过可选 extras 安装：``pip install -e '.[sherpa]'``。
"""

from __future__ import annotations

import array
import wave
from pathlib import Path

from ..config import AsrConfig


class SherpaError(RuntimeError):
    """sherpa-onnx 后端错误。"""


def _read_pcm_wav(path: Path) -> tuple[int, array.array]:
    """用标准库读取 16bit 单声道 PCM WAV，返回 (采样率, float32 采样序列)。"""
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
    except wave.Error as exc:
        raise SherpaError(f"无法读取 WAV（需要未压缩 PCM 格式）：{path} ({exc})") from exc

    if channels != 1:
        raise SherpaError(f"仅支持单声道 WAV，当前为 {channels} 声道：{path}")
    if sample_width != 2:
        raise SherpaError(f"仅支持 16bit PCM，当前采样宽度 {sample_width} 字节：{path}")

    # array('h') 按 16bit 有符号整数解析，再归一化到 [-1, 1) 的 float32
    ints = array.array("h", pcm)
    samples = array.array("f", (s / 32768.0 for s in ints))
    return sample_rate, samples


class SherpaAsr:
    """SenseVoice 离线识别器（每次 CLI 调用一个进程，加载约 0.4s）。"""

    def __init__(self, cfg: AsrConfig) -> None:
        self.cfg = cfg
        try:
            import sherpa_onnx  # 延迟导入，无该依赖时仍可使用 openai/mock 后端
        except ModuleNotFoundError as exc:
            raise SherpaError(
                "未安装 sherpa-onnx，请执行：.venv/bin/pip install -e '.[sherpa]'"
            ) from exc
        self._sherpa_onnx = sherpa_onnx

        model_dir = Path(cfg.sherpa_model_dir).expanduser()
        self.model_file = model_dir / "model.int8.onnx"
        self.tokens_file = model_dir / "tokens.txt"
        if not self.model_file.exists() or not self.tokens_file.exists():
            raise SherpaError(
                f"SenseVoice 模型文件缺失：{model_dir}（需要 model.int8.onnx 与 tokens.txt）"
            )

    def _build_recognizer(self):
        return self._sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(self.model_file),
            tokens=str(self.tokens_file),
            num_threads=self.cfg.sherpa_num_threads,
            use_itn=self.cfg.sherpa_use_itn,
            # zh / en / auto / ja / ko / yue
            language=self.cfg.language or "auto",
        )

    def transcribe(self, wav_path: Path) -> str:
        sample_rate, samples = _read_pcm_wav(wav_path)
        recognizer = self._build_recognizer()
        stream = recognizer.create_stream()
        # 采样率与模型不一致时 sherpa-onnx 内部会重采样
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
