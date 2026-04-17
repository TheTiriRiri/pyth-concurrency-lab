"""Experiment 04 — speedup vs worker count. The headline chart.

Hypothesis:
    threading: flat line (GIL serialises all Python bytecode).
    multiprocessing: descending from 1 worker down to ≈ cpu_count, then plateaus (Amdahl).
    asyncio: flat (single thread, to_thread still GIL-bound for CPU work).

Params reduced from the original plan (N_TASKS=16, n_repeats=5 → N_TASKS=8, n_repeats=3)
to keep total runtime ~5 min on a 20-core machine. The qualitative chart shape — the
entire point of this experiment — is preserved.
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from lab.plot import scaling_line
from lab.runner import measure
from lab.workloads import count_primes_up_to

EXPERIMENT = "04_scaling"
LIMIT = 1_000_000
N_TASKS = 8
WORKER_LEVELS = [1, 2, 4, 8, 16, 32]

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
CSV_PATH = RESULTS_DIR / f"{EXPERIMENT}.csv"
PNG_PATH = RESULTS_DIR / f"{EXPERIMENT}.png"


def _make_threading(workers: int):
    def _fn(**_):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(count_primes_up_to, [LIMIT] * N_TASKS))
    return _fn


def _make_multiprocessing(workers: int):
    def _fn(**_):
        with ProcessPoolExecutor(max_workers=workers) as pool:
            list(pool.map(count_primes_up_to, [LIMIT] * N_TASKS))
    return _fn


def _make_asyncio(workers: int):
    async def _fn(**_):
        sem = asyncio.Semaphore(workers)

        async def _task():
            async with sem:
                await asyncio.to_thread(count_primes_up_to, LIMIT)

        await asyncio.gather(*[_task() for _ in range(N_TASKS)])
    return _fn


def main() -> None:
    print(f"=== {EXPERIMENT} ===")
    print(f"Python {sys.version.split()[0]} · {platform.processor() or 'unknown CPU'} · {os.cpu_count()} cores")
    print(f"Workload: count_primes_up_to({LIMIT}) × {N_TASKS}; workers ∈ {WORKER_LEVELS}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        CSV_PATH.unlink()

    factories = {
        "threading": _make_threading,
        "multiprocessing": _make_multiprocessing,
        "asyncio": _make_asyncio,
    }

    for paradigm, factory in factories.items():
        for workers in WORKER_LEVELS:
            print(f"  {paradigm:<18} workers={workers:>3} ", end=" ", flush=True)
            m = measure(
                experiment=EXPERIMENT,
                paradigm=paradigm,
                fn=factory(workers),
                workers=workers,
                n_tasks=N_TASKS,
                csv_path=CSV_PATH,
                n_repeats=3,
                warmup=True,
            )
            print(f"{m.duration_s:6.2f}s  CPU={m.cpu_percent_avg:5.0f}%  mem={m.mem_mb_peak:5.0f}MB")

    scaling_line(CSV_PATH, PNG_PATH)
    print(f"\nChart: {PNG_PATH}")


if __name__ == "__main__":
    main()
