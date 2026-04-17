"""Experiment 05 — mixed I/O + CPU workload; hybrid asyncio+executor wins.

Hypothesis:
    For fetch → hash → write pipelines, a pure paradigm underperforms a hybrid
    that uses asyncio for the network legs and a ProcessPoolExecutor (via
    loop.run_in_executor) for the CPU-bound hashing.
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import httpx

from lab.mock_server import MockServer
from lab.plot import compare_bar
from lab.runner import measure
from lab.workloads import count_primes_up_to

EXPERIMENT = "05_mixed"
N_ITERATIONS = 50
PAYLOAD_BYTES = 100_000
# The CPU leg uses count_primes_up_to() instead of hash_bytes(): SHA-256 is
# so fast that even 500 rounds take <1 ms, masking the point of the experiment.
# count_primes_up_to(N) gives us predictable, meaningful CPU work where the
# GIL-bypass advantage of run_in_executor becomes visible.
CPU_LIMIT = 300_000
WORKERS = 8

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
OUT_DIR = RESULTS_DIR / "_mixed_out"
CSV_PATH = RESULTS_DIR / f"{EXPERIMENT}.csv"
PNG_PATH = RESULTS_DIR / f"{EXPERIMENT}.png"

_BASE_URL = ""


def _url() -> str:
    return f"{_BASE_URL}/payload/{PAYLOAD_BYTES}"


def _pipeline_step_sync(i: int) -> None:
    with httpx.Client(timeout=30) as client:
        _ = client.get(_url()).content  # I/O leg — payload itself is not used
    primes = count_primes_up_to(CPU_LIMIT)  # CPU leg
    (OUT_DIR / f"{i:04d}.txt").write_text(f"primes={primes}")


def _cpu_only(limit: int) -> int:
    return count_primes_up_to(limit)


def run_threading(**_):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_pipeline_step_sync, range(N_ITERATIONS)))


def run_multiprocessing(**_):
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_pipeline_step_sync, range(N_ITERATIONS)))


async def run_asyncio_blocking(**_):
    # Anti-pattern: blocking count_primes inside the event loop.
    async with httpx.AsyncClient(timeout=30) as client:
        async def _task(i: int):
            _ = (await client.get(_url())).content
            primes = count_primes_up_to(CPU_LIMIT)  # blocks loop for ~1s
            (OUT_DIR / f"{i:04d}.txt").write_text(f"primes={primes}")
        await asyncio.gather(*[_task(i) for i in range(N_ITERATIONS)])


async def run_asyncio_hybrid(**_):
    # Correct pattern: offload CPU to a process pool via run_in_executor.
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        async with httpx.AsyncClient(timeout=30) as client:
            async def _task(i: int):
                _ = (await client.get(_url())).content
                primes = await loop.run_in_executor(pool, _cpu_only, CPU_LIMIT)
                (OUT_DIR / f"{i:04d}.txt").write_text(f"primes={primes}")
            await asyncio.gather(*[_task(i) for i in range(N_ITERATIONS)])


def main() -> None:
    global _BASE_URL
    print(f"=== {EXPERIMENT} ===")
    print(f"Python {sys.version.split()[0]} · {platform.processor() or 'unknown CPU'} · {os.cpu_count()} cores")
    print(f"Workload: {N_ITERATIONS} × (fetch {PAYLOAD_BYTES}B → count_primes({CPU_LIMIT}) → write)")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        CSV_PATH.unlink()

    with MockServer() as server:
        _BASE_URL = server.base_url
        for paradigm, fn, label in (
            ("threading", run_threading, "threading"),
            ("multiprocessing", run_multiprocessing, "multiprocessing"),
            ("asyncio", run_asyncio_blocking, "asyncio (blocking hash)"),
            ("asyncio", run_asyncio_hybrid, "asyncio + executor"),
        ):
            print(f"  {label:<28}", end=" ", flush=True)
            m = measure(
                experiment=EXPERIMENT,
                paradigm=label,  # override paradigm label for distinct bars
                fn=fn,
                workers=WORKERS,
                n_tasks=N_ITERATIONS,
                csv_path=CSV_PATH,
                n_repeats=3,
                warmup=True,
            )
            print(f"{m.duration_s:6.2f}s  CPU={m.cpu_percent_avg:5.0f}%  mem={m.mem_mb_peak:5.0f}MB")

    compare_bar(CSV_PATH, PNG_PATH, metric="duration_s")
    print(f"\nChart: {PNG_PATH}")


if __name__ == "__main__":
    main()
