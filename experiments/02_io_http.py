"""Experiment 02 — asyncio dominates HTTP I/O.

Hypothesis:
    asyncio ≥ threading >> multiprocessing >> sequential for N network requests
    when each request mostly waits on the server.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import httpx

from lab.mock_server import MockServer
from lab.plot import compare_bar
from lab.runner import measure
from lab.workloads import fetch_url_async, fetch_url_sync

EXPERIMENT = "02_io_http"
N_REQUESTS = 100
DELAY_S = 1.0

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
CSV_PATH = RESULTS_DIR / f"{EXPERIMENT}.csv"
PNG_PATH = RESULTS_DIR / f"{EXPERIMENT}.png"


# Globals wired by main() before experiments run.
_BASE_URL = ""


def _url() -> str:
    return f"{_BASE_URL}/delay/{DELAY_S}"


def run_sequential(**_):
    with httpx.Client(timeout=30) as client:
        for _ in range(N_REQUESTS):
            fetch_url_sync(client, _url())


# Per-process httpx.Client so each worker amortises connection setup across
# its calls — symmetric to the single shared client used in run_threading.
# Without this, multiprocessing would pay a fresh TCP handshake per request
# and the comparison against threading would be unfair.
_WORKER_CLIENT: httpx.Client | None = None


def _proc_init() -> None:
    global _WORKER_CLIENT
    _WORKER_CLIENT = httpx.Client(timeout=30)


def _fetch_worker(url: str) -> int:
    assert _WORKER_CLIENT is not None, "ProcessPoolExecutor must use _proc_init"
    return fetch_url_sync(_WORKER_CLIENT, url)


def run_threading(workers: int, **_):
    with httpx.Client(timeout=30) as client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda u: fetch_url_sync(client, u), [_url()] * N_REQUESTS))


def run_multiprocessing(workers: int, **_):
    with ProcessPoolExecutor(max_workers=workers, initializer=_proc_init) as pool:
        list(pool.map(_fetch_worker, [_url()] * N_REQUESTS))


async def run_asyncio(**_):
    # Client MUST be constructed inside the coroutine (fresh event loop per
    # measure() call). Module-scope AsyncClients would break after the first
    # run because their loop would be closed.
    async with httpx.AsyncClient(timeout=30) as client:
        await asyncio.gather(*[fetch_url_async(client, _url()) for _ in range(N_REQUESTS)])


def main() -> None:
    global _BASE_URL

    parser = argparse.ArgumentParser()
    parser.add_argument("--external", action="store_true",
                        help="Target httpbin.org instead of the local mock server.")
    args = parser.parse_args()

    print(f"=== {EXPERIMENT} ===")
    print(f"Python {sys.version.split()[0]} · {platform.processor() or 'unknown CPU'} · {os.cpu_count()} cores")
    print(f"Workload: {N_REQUESTS} × GET /delay/{DELAY_S}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        CSV_PATH.unlink()

    if args.external:
        _BASE_URL = "https://httpbin.org"
        _run_experiments()
    else:
        with MockServer() as server:
            _BASE_URL = server.base_url
            _run_experiments()

    compare_bar(CSV_PATH, PNG_PATH, metric="duration_s")
    print(f"\nChart: {PNG_PATH}")


def _run_experiments() -> None:
    plans = [
        ("sequential", run_sequential, 1),
        ("threading", run_threading, 16),
        ("threading", run_threading, 64),
        ("multiprocessing", run_multiprocessing, 16),
        ("asyncio", run_asyncio, N_REQUESTS),
    ]
    for paradigm, fn, workers in plans:
        label = f"{paradigm}({workers})"
        print(f"  {label:<22}", end=" ", flush=True)
        # Wrap fn in a closure that captures workers — keeps Metrics.workers
        # accurate without aliasing kwargs with measure()'s own `workers` param.
        if inspect.iscoroutinefunction(fn):
            async def _wrapped(_fn=fn, _w=workers, **_):
                await _fn(workers=_w)
        else:
            def _wrapped(_fn=fn, _w=workers, **_):
                _fn(workers=_w)

        m = measure(
            experiment=EXPERIMENT,
            paradigm=paradigm,
            fn=_wrapped,
            workers=workers,
            n_tasks=N_REQUESTS,
            csv_path=CSV_PATH,
            n_repeats=3,
            warmup=True,
        )
        print(f"{m.duration_s:6.2f}s  CPU={m.cpu_percent_avg:5.0f}%  mem={m.mem_mb_peak:5.0f}MB")


if __name__ == "__main__":
    main()
