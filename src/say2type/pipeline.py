"""端到端流水线编排：录音文件 -> ASR -> LLM 清洗 -> 光标注入。"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .asr.client import AsrClient
from .config import AppConfig
from .injector.macos import inject_paste
from .llm.cleaner import LlmCleaner, build_system_prompt


@dataclass
class PipelineResult:
    raw_text: str
    final_text: str
    asr_ms: int
    llm_ms: int
    total_ms: int


def process_wav(wav_path: Path, cfg: AppConfig, *, inject: bool = True) -> PipelineResult:
    t_start = time.perf_counter()

    t0 = time.perf_counter()
    raw_text = AsrClient(cfg.asr).transcribe(wav_path)
    asr_ms = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    if cfg.llm.enabled and raw_text:
        system_prompt = build_system_prompt(cfg)
        final_text = LlmCleaner(cfg.llm, system_prompt).clean(raw_text)
    else:
        final_text = raw_text
    llm_ms = int((time.perf_counter() - t0) * 1000)

    total_ms = int((time.perf_counter() - t_start) * 1000)

    if inject and cfg.injector.enabled and final_text:
        inject_paste(final_text, cfg.injector)

    return PipelineResult(
        raw_text=raw_text,
        final_text=final_text,
        asr_ms=asr_ms,
        llm_ms=llm_ms,
        total_ms=total_ms,
    )


def report_timing(result: PipelineResult, *, injected: bool) -> None:
    """把耗时与文本打到 stderr，避免污染 stdout 的纯文本输出。"""
    sys.stderr.write(
        f"[say2type] ASR {result.asr_ms}ms | LLM {result.llm_ms}ms | "
        f"合计 {result.total_ms}ms | 去向: {'已注入光标' if injected else '标准输出'}\n"
    )
    if result.raw_text != result.final_text:
        sys.stderr.write(f"[say2type] ASR 原文: {result.raw_text}\n")
    sys.stderr.write(f"[say2type] 最终文本: {result.final_text}\n")
