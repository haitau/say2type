"""本地 LLM 文本清洗。

调用 OpenAI 兼容的 ``/v1/chat/completions``（Ollama、oMLX 均支持），
把 ASR 产出的口语草稿清洗为可直接上屏的书面文本。
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib import error, request

from ..config import LlmConfig, resolve_rule_path, AppConfig


class LlmError(RuntimeError):
    """LLM 服务调用失败。"""


def load_custom_vocab(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """解析词表文件。

    支持两种行格式（# 开头为注释）：

    * ``Docker``                —— 提示模型该术语必须保持规范写法
    * ``杰森=JSON``             —— 显式的同音/口误映射
    """
    terms: list[str] = []
    mappings: list[tuple[str, str]] = []
    if not path.exists():
        return terms, mappings
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            wrong, right = (part.strip() for part in line.split("=", 1))
            if wrong and right:
                mappings.append((wrong, right))
        else:
            terms.append(line)
    return terms, mappings


def build_system_prompt(cfg: AppConfig) -> str:
    prompt_path = resolve_rule_path(cfg, cfg.rules.system_prompt)
    if not prompt_path.exists():
        raise LlmError(f"System Prompt 文件不存在：{prompt_path}")
    parts = [prompt_path.read_text(encoding="utf-8").strip()]

    vocab_path = resolve_rule_path(cfg, cfg.rules.custom_vocab)
    terms, mappings = load_custom_vocab(vocab_path)
    if terms:
        parts.append("## 必须保持规范写法的技术术语\n" + "、".join(terms))
    if mappings:
        mapping_lines = "\n".join(f"- 遇到“{wrong}”应写为 {right}" for wrong, right in mappings)
        parts.append("## 同音/口误纠正映射\n" + mapping_lines)
    return "\n\n".join(parts)


class LlmCleaner:
    def __init__(self, cfg: LlmConfig, system_prompt: str) -> None:
        self.cfg = cfg
        self.system_prompt = system_prompt

    def clean(self, raw_text: str) -> str:
        raw_text = raw_text.strip()
        if not raw_text:
            return ""
        if not self.cfg.enabled:
            return raw_text
        if self.cfg.backend == "mock":
            return raw_text
        if self.cfg.backend != "openai":
            raise LlmError(f"未知 LLM backend: {self.cfg.backend}")
        return self._chat_openai(raw_text)

    def _chat_openai(self, raw_text: str) -> str:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": raw_text},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=self.cfg.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except error.URLError as exc:
            raise LlmError(
                f"无法连接 LLM 服务 {url}：{exc.reason}。"
                "请确认 Ollama/oMLX 已启动并已拉取模型，或临时将 [llm] enabled 设为 false。"
            ) from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LlmError(f"LLM 服务返回 HTTP {exc.code}：{detail}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"LLM 响应结构异常：{data}") from exc
        return content.strip()
