"""Experiment 03 — disk I/O: threading ≈ asyncio, multiprocessing pays overhead."""
from __future__ import annotations

import asyncio
import os
import platform
import random
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from lab.plot import compare_bar
from lab.runner import measure
from lab.workloads import read_file_async, read_file_sync

EXPERIMENT = "03_io_disk"
N_FILES = 200
FILE_SIZE_BYTES = 1_000_000
WORKERS = 16

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
TMP_DIR = ROOT / "tmp_data"
CSV_PATH = RESULTS_DIR / f"{EXPERIMENT}.csv"
PNG_PATH = RESULTS_DIR / f"{EXPERIMENT}.png"


def _ensure_files() -> list[Path]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(TMP_DIR.glob("file_*.bin"))
    if len(existing) >= N_FILES:
        return existing[:N_FILES]

    print(f"  setup: generating {N_FILES} × {FILE_SIZE_BYTES // 1024}KB files...", flush=True)
    rng = random.Random(42)
    for i in range(len(existing), N_FILES):
        (TMP_DIR / f"file_{i:04d}.bin").write_bytes(bytes(rng.randrange(256) for _ in range(FILE_SIZE_BYTES)))
    return sorted(TMP_DIR.glob("file_*.bin"))[:N_FILES]


_FILES: list[Path] = []


def run_sequential(**_):
    for p in _FILES:
        read_file_sync(p)


def run_threading(**_):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(read_file_sync, _FILES))


def run_multiprocessing(**_):
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(read_file_sync, _FILES))


async def run_asyncio(**_):
    await asyncio.gather(*[read_file_async(p) for p in _FILES])


def main() -> None:
    global _FILES
    print(f"=== {EXPERIMENT} ===")
    print(f"Python {sys.version.split()[0]} · {platform.processor() or 'unknown CPU'} · {os.cpu_count()} cores")
    print(f"Workload: read {N_FILES} × {FILE_SIZE_BYTES // 1024}KB files (workers={WORKERS})")

    _FILES = _ensure_files()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        CSV_PATH.unlink()

    for paradigm, fn in (
        ("sequential", run_sequential),
        ("threading", run_threading),
        ("multiprocessing", run_multiprocessing),
        ("asyncio", run_asyncio),
    ):
        workers = 1 if paradigm == "sequential" else WORKERS
        print(f"  {paradigm:<18}", end=" ", flush=True)
        m = measure(
            experiment=EXPERIMENT,
            paradigm=paradigm,
            fn=fn,
            workers=workers,
            n_tasks=N_FILES,
            csv_path=CSV_PATH,
            n_repeats=3,
            warmup=True,
        )
        print(f"{m.duration_s:6.3f}s  CPU={m.cpu_percent_avg:5.0f}%  mem={m.mem_mb_peak:5.0f}MB")

    compare_bar(CSV_PATH, PNG_PATH, metric="duration_s")
    print(f"\nChart: {PNG_PATH}")


if __name__ == "__main__":
    main()
