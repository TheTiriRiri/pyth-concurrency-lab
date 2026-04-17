"""Measurement runner for concurrency experiments.

Timing + optional psutil sampling. Paradigm-agnostic — receives a plain Callable
(or coroutine function) and runs it once, capturing duration, CPU, and peak RSS.
"""
from __future__ import annotations

import asyncio
import inspect
import time
import traceback
from pathlib import Path
from typing import Callable

from lab.metrics import Metrics, append_csv


def measure(
    experiment: str,
    paradigm: str,
    fn: Callable,
    workers: int,
    n_tasks: int,
    csv_path: Path | None = None,
    sample_interval_s: float = 0.05,
    **params,
) -> Metrics:
    """Run fn(**params) once, returning a Metrics record.

    NOTE: If fn is async, any httpx.AsyncClient / aiohttp.ClientSession must be
    constructed INSIDE fn — each call gets a fresh event loop via asyncio.run().
    """
    is_coro = inspect.iscoroutinefunction(fn)
    extra: dict = {}
    start = time.perf_counter()
    try:
        if is_coro:
            asyncio.run(fn(**params))
        else:
            fn(**params)
        duration = time.perf_counter() - start
    except Exception as exc:  # noqa: BLE001 — intentional broad catch for lab
        duration = -1.0
        extra["error"] = f"{type(exc).__name__}: {exc}"
        extra["traceback"] = traceback.format_exc()

    m = Metrics(
        experiment=experiment,
        paradigm=paradigm,
        workers=workers,
        n_tasks=n_tasks,
        duration_s=duration,
        cpu_percent_avg=0.0,  # filled in Task 4
        mem_mb_peak=0.0,      # filled in Task 4
        extra=extra,
    )
    if csv_path is not None:
        append_csv(csv_path, m)
    return m
