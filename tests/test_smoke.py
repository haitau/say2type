"""冒烟测试：python3 -m unittest discover -s tests -v

sherpa-onnx 相关用例在缺少依赖或模型时自动跳过。
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from say2type.asr.client import _build_multipart  # noqa: E402
from say2type.config import load_config  # noqa: E402
from say2type.llm.cleaner import build_system_prompt, load_custom_vocab  # noqa: E402

HAS_SHERPA = importlib.util.find_spec("sherpa_onnx") is not None
SENSE_VOICE_DIR = Path.home() / ".voice-record/models/sherpa-onnx-sense-voice-small"


class ConfigTests(unittest.TestCase):
    def test_load_example_config(self) -> None:
        cfg = load_config(ROOT / "config.example.toml")
        self.assertEqual(cfg.audio.sample_rate, 16000)
        self.assertEqual(cfg.asr.backend, "sherpa")
        self.assertIn("sense-voice", cfg.asr.sherpa_model_dir)
        self.assertIn("8000", cfg.llm.base_url)
        self.assertEqual(cfg.llm.model, "Qwen3-VL-8B-Instruct-4bit")
        self.assertTrue(cfg.injector.enabled)

    def test_defaults_without_file(self) -> None:
        # 不存在的路径会抛错；无参数时在仓库根目录应能找到 example 之外的默认值
        cfg = load_config(None)
        self.assertIsInstance(cfg.audio.sample_rate, int)


class PromptTests(unittest.TestCase):
    def test_vocab_parsing(self) -> None:
        vocab = ROOT / "rules" / "custom_vocab.txt"
        terms, mappings = load_custom_vocab(vocab)
        self.assertIn("Git", terms)
        self.assertIn(("docker", "Docker"), mappings)
        self.assertIn(("杰森", "JSON"), mappings)

    def test_system_prompt_assembly(self) -> None:
        cfg = load_config(ROOT / "config.example.toml")
        prompt = build_system_prompt(cfg)
        self.assertIn("语音输入文本校正引擎", prompt)
        self.assertIn("JSON", prompt)  # 词表映射被装配进来


class MultipartTests(unittest.TestCase):
    def test_multipart_contains_wav(self) -> None:
        wav = ROOT / "tests" / "fixtures" / "fake.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        wav.write_bytes(b"RIFFxxxxWAVEfmt ")  # 占位字节，仅验证拼装结构
        body, boundary = _build_multipart({"model": "whisper-1"}, "file", wav)
        self.assertIn(f"--{boundary}".encode(), body)
        self.assertIn(b'name="model"', body)
        self.assertIn(b'filename="fake.wav"', body)
        self.assertIn(b"RIFFxxxxWAVEfmt ", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))


@unittest.skipUnless(
    HAS_SHERPA and (SENSE_VOICE_DIR / "model.int8.onnx").exists(),
    "需要 sherpa-onnx 与本地 SenseVoice 模型",
)
class SherpaIntegrationTests(unittest.TestCase):
    def test_sense_voice_transcribe(self) -> None:
        from say2type.asr.sherpa_backend import SherpaAsr
        from say2type.config import AsrConfig

        cfg = AsrConfig(
            sherpa_model_dir=str(SENSE_VOICE_DIR),
            language="zh",
        )
        wav = SENSE_VOICE_DIR / "morning_scene.wav"
        text = SherpaAsr(cfg).transcribe(wav)
        self.assertIn("阳光", text)


if __name__ == "__main__":
    unittest.main()
