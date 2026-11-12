"""本地 ASR 客户端。

默认走 OpenAI 兼容的 ``/v1/audio/transcriptions`` 接口，适配：

* faster-whisper-server
* mlx-omni-server（oMLX 生态）
* 任何自托管的 OpenAI 兼容语音服务

零第三方依赖，multipart/form-data 用标准库 urllib 手工拼装。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib import error, request

from ..config import AsrConfig


class AsrError(RuntimeError):
    """ASR 服务调用失败。"""


def _build_multipart(
    fields: dict[str, str], file_field: str, file_path: Path
) -> tuple[bytes, str]:
    boundary = f"----say2type-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        body.extend(str(value).encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_path.name}"\r\n'.encode()
    )
    body.extend(b"Content-Type: audio/wav\r\n\r\n")
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), boundary


class AsrClient:
    def __init__(self, cfg: AsrConfig) -> None:
        self.cfg = cfg

    def transcribe(self, wav_path: Path) -> str:
        if not self.cfg.enabled:
            return ""
        if self.cfg.backend == "mock":
            return (
                "呃那个，我们今天来说一下 docker 配合 k8s 的部署方式，"
                "就是说，先写好 dockerfile，然后用 JSON 配置流水线。"
            )
        if self.cfg.backend == "sherpa":
            from .sherpa_backend import SherpaAsr

            return SherpaAsr(self.cfg).transcribe(wav_path)
        if self.cfg.backend != "openai":
            raise AsrError(f"未知 ASR backend: {self.cfg.backend}")
        return self._transcribe_openai(wav_path)

    def _transcribe_openai(self, wav_path: Path) -> str:
        url = self.cfg.base_url.rstrip("/") + "/audio/transcriptions"
        fields = {
            "model": self.cfg.model,
            "response_format": "json",
        }
        if self.cfg.language:
            fields["language"] = self.cfg.language
        if self.cfg.extra_prompt:
            fields["prompt"] = self.cfg.extra_prompt

        body, boundary = _build_multipart(fields, "file", wav_path)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = request.Request(url, data=body, method="POST", headers=headers)
        try:
            with request.urlopen(req, timeout=self.cfg.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.URLError as exc:
            raise AsrError(
                f"无法连接 ASR 服务 {url}：{exc.reason}。"
                "请确认本地识别服务已启动，或将 [asr] backend 设为 \"mock\" 先联调。"
            ) from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AsrError(f"ASR 服务返回 HTTP {exc.code}：{detail}") from exc

        text = (payload.get("text") or "").strip()
        if not text:
            raise AsrError(f"ASR 返回空文本，原始响应：{payload}")
        return text
