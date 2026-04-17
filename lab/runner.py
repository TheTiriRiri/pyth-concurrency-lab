"""Measurement runner for concurrency experiments."""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

import psutil

from lab.metrics import Metrics, append_csv


class _Sampler:
    """Background sampler that aggregates CPU% and RSS across parent + children.

    cpu_percent() is per-process and excludes children — a naive parent-only
    sampler would silently report ~0% for multiprocessing workloads. We therefore
    sum cpu_percent and memory across parent + every live descendant on each tick.
    """

    def __init__(self, interval_s: float):
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._parent = psutil.Process()
        # Cache Process objects by PID. psutil.Process.cpu_percent() tracks
        # per-object state (CPU times since the last call ON THIS OBJECT), so
        # we MUST reuse the same Process instance across ticks — otherwise every
        # child's first call returns 0.0 and we never measure their real CPU.
        self._tracked: dict[int, psutil.Process] = {}
        self._primed: set[int] = set()
        self._cpu_samples: list[float] = []
        self._mem_peak_mb = 0.0

    def _get_tracked(self, pid: int) -> psutil.Process | None:
        """Return cached Process for pid, creating+priming if new."""
        proc = self._tracked.get(pid)
        if proc is None:
            try:
                proc = psutil.Process(pid)
            except psutil.NoSuchProcess:
                return None
            self._tracked[pid] = proc
        return proc

    def _prime(self, proc: psutil.Process) -> None:
        """psutil requires an initial cpu_percent() call to establish baseline."""
        if proc.pid in self._primed:
            return
        try:
            proc.cpu_percent(interval=None)
            self._primed.add(proc.pid)
        except psutil.NoSuchProcess:
            pass

    def _snapshot(self) -> tuple[float, float]:
        # Always track the parent via the cached instance.
        pids = [self._parent.pid]
        try:
            pids.extend(c.pid for c in self._parent.children(recursive=True))
        except psutil.NoSuchProcess:
            return 0.0, 0.0
        # Ensure parent is in the cache.
        self._tracked.setdefault(self._parent.pid, self._parent)

        cpu_total = 0.0
        mem_total_mb = 0.0
        for pid in pids:
            proc = self._get_tracked(pid)
            if proc is None:
                self._primed.discard(pid)
                continue
            try:
                if pid not in self._primed:
                    self._prime(proc)
                    continue  # first call always returns 0; skip this sample
                cpu_total += proc.cpu_percent(interval=None)
                mem_total_mb += proc.memory_info().rss / (1024 * 1024)
            except psutil.NoSuchProcess:
                self._primed.discard(pid)
                self._tracked.pop(pid, None)
        return cpu_total, mem_total_mb

    def _run(self) -> None:
        # Prime the parent immediately so the first real sample is meaningful.
        self._prime(self._parent)
        while not self._stop.is_set():
            cpu, mem = self._snapshot()
            if cpu > 0.0:
                self._cpu_samples.append(cpu)
            if mem > self._mem_peak_mb:
                self._mem_peak_mb = mem
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> tuple[float, float]:
        self._stop.set()
        self._thread.join(timeout=2.0)
        cpu_avg = sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else 0.0
        return cpu_avg, self._mem_peak_mb


def _measure_once(
    experiment: str,
    paradigm: str,
    fn: Callable,
    workers: int,
    n_tasks: int,
    sample_interval_s: float,
    is_coro: bool,
    params: dict,
) -> Metrics:
    extra: dict = {}
    sampler = _Sampler(sample_interval_s)
    sampler.start()
    start = time.perf_counter()
    try:
        if is_coro:
            asyncio.run(fn(**params))
        else:
            fn(**params)
        duration = round(time.perf_counter() - start, 6)
    except Exception as exc:  # noqa: BLE001
        duration = -1.0
        extra["error"] = f"{type(exc).__name__}: {exc}"
        extra["traceback"] = traceback.format_exc()
    cpu_avg, mem_peak = sampler.stop()
    return Metrics(
        experiment=experiment,
        paradigm=paradigm,
        workers=workers,
        n_tasks=n_tasks,
        duration_s=duration,
        cpu_percent_avg=cpu_avg,
        mem_mb_peak=mem_peak,
        extra=extra,
    )


def measure(
    experiment: str,
    paradigm: str,
    fn: Callable,
    workers: int,
    n_tasks: int,
    csv_path: Path | None = None,
    sample_interval_s: float = 0.05,
    n_repeats: int = 1,
    warmup: bool = False,
    **params,
) -> Metrics:
    """Run fn(**params) `n_repeats` times, return the median Metrics.

    When `warmup=True`, one un-recorded call precedes the timed repeats to warm
    caches and JITs. Each recorded run is appended to `csv_path` (if given) as a
    separate row tagged with `extra["repeat_idx"] = i`.

    NOTE: If fn is async, any httpx.AsyncClient / aiohttp.ClientSession must be
    constructed INSIDE fn — each call gets a fresh event loop via asyncio.run().
    """
    is_coro = inspect.iscoroutinefunction(fn)

    if warmup:
        _measure_once(experiment, paradigm, fn, workers, n_tasks,
                      sample_interval_s, is_coro, params)

    results: list[Metrics] = []
    for i in range(n_repeats):
        m = _measure_once(experiment, paradigm, fn, workers, n_tasks,
                          sample_interval_s, is_coro, params)
        m.extra["repeat_idx"] = i
        if csv_path is not None:
            append_csv(csv_path, m)
        results.append(m)

    # Median by duration; ties broken by lowest index.
    sorted_by_duration = sorted(results, key=lambda x: x.duration_s)
    median_idx = len(sorted_by_duration) // 2
    return sorted_by_duration[median_idx]
