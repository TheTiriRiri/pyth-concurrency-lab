"""Experiment 01 — GIL kills threading for CPU-bound work.

Hypothesis:
    For CPU-bound code, threading ≈ sequential (no speedup, often slower),
    multiprocessing ~N× faster up to CPU count, asyncio ≈ sequential.
"""
from __future__ import annotations

import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from lab.plot import compare_bar
from lab.runner import measure
from lab.workloads import count_primes_up_to

EXPERIMENT = "01_cpu_primes"
LIMIT = 2_000_000
N_TASKS = 4
WORKERS = 4

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
CSV_PATH = RESULTS_DIR / f"{EXPERIMENT}.csv"
PNG_PATH = RESULTS_DIR / f"{EXPERIMENT}.png"


def run_sequential(**_):
    for _ in range(N_TASKS):
        count_primes_up_to(LIMIT)


def run_threading(**_):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(count_primes_up_to, [LIMIT] * N_TASKS))


def run_multiprocessing(**_):
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(count_primes_up_to, [LIMIT] * N_TASKS))


async def run_asyncio(**_):
    import asyncio
    # asyncio cannot parallelise CPU work in a single thread — to_thread still
    # serialises through the GIL. This is the lesson.
    await asyncio.gather(*[asyncio.to_thread(count_primes_up_to, LIMIT) for _ in range(N_TASKS)])


def main() -> None:
    print(f"=== {EXPERIMENT} ===")
    print(f"Python {sys.version.split()[0]} · {platform.processor() or 'unknown CPU'} · {os.cpu_count()} cores")
    print(f"Workload: count_primes_up_to({LIMIT}) × {N_TASKS}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        CSV_PATH.unlink()  # fresh comparison per run

    for paradigm, fn in (
        ("sequential", run_sequential),
        ("threading", run_threading),
        ("multiprocessing", run_multiprocessing),
        ("asyncio", run_asyncio),
    ):
        workers = 1 if paradigm == "sequential" else WORKERS
        print(f"  {paradigm}...", end=" ", flush=True)
        m = measure(
            experiment=EXPERIMENT,
            paradigm=paradigm,
            fn=fn,
            workers=workers,
            n_tasks=N_TASKS,
            csv_path=CSV_PATH,
            n_repeats=5,
            warmup=True,
        )
        print(f"{m.duration_s:.2f}s  CPU={m.cpu_percent_avg:.0f}%  mem={m.mem_mb_peak:.0f}MB")

    compare_bar(CSV_PATH, PNG_PATH, metric="duration_s")
    print(f"\nChart: {PNG_PATH}")


if __name__ == "__main__":
    main()
