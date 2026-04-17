# Concurrency Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hands-on Python laboratory proving on real measurements when to use `threading`, `multiprocessing`, and `asyncio`, with 5 experiments + 6 pitfall demos, a shared measurement engine, and matplotlib charts that back each hypothesis.

**Architecture:** Paradigm-agnostic engine in `lab/` (metrics dataclass, runner with psutil-based sampling that aggregates parent + child processes, plotter, pure workload functions, local aiohttp mock server) + one standalone script per experiment that wires the same workload into three concurrency strategies and funnels each through `runner.measure()`. Data flows as `experiment → runner → Metrics → CSV → plot → PNG`. Pitfalls are isolated teaching artefacts.

**Tech Stack:** Python 3.12, httpx 0.27.2, aiofiles 24.1.0, aiohttp 3.10.10, psutil 6.1.0, matplotlib 3.9.2, pytest 8.3.3. Linux target (POSIX-only behaviour acceptable per spec §8).

**Spec:** `docs/superpowers/specs/2026-04-17-concurrency-lab-design.md`

---

## File Structure

Files that will be created, grouped by responsibility:

**Engine (`lab/`):**
- `lab/__init__.py` — package marker, exports public API
- `lab/metrics.py` — `Metrics` dataclass + `append_csv` / `load_csv`
- `lab/workloads.py` — pure paradigm-agnostic functions
- `lab/runner.py` — `measure()`, psutil sampler, child-process aggregation, n_repeats/median
- `lab/plot.py` — `compare_bar`, `scaling_line`
- `lab/mock_server.py` — local aiohttp server with `/delay/{s}` and `/payload/{n}`

**Experiments (`experiments/`):**
- `experiments/01_cpu_primes.py`
- `experiments/02_io_http.py`
- `experiments/03_io_disk.py`
- `experiments/04_scaling.py`
- `experiments/05_mixed.py`

**Pitfalls (`pitfalls/`):**
- `pitfalls/01_race_condition_broken.py` + `_fixed.py`
- `pitfalls/02_deadlock_broken.py` + `_fixed.py`
- `pitfalls/03_gil_demo.py`
- `pitfalls/04_async_blocking_broken.py` + `_fixed.py`
- `pitfalls/05_pickle_broken.py` + `_fixed.py`
- `pitfalls/06_gather_vs_taskgroup.py`

**Tests (`tests/`):**
- `tests/conftest.py` — shared fixtures (tmp CSV paths, mock HTTP server)
- `tests/test_metrics.py`
- `tests/test_workloads.py`
- `tests/test_runner.py`
- `tests/test_plot.py`

**Tooling:**
- `requirements.txt`
- `Makefile`
- `.gitignore`
- `pytest.ini`
- `README.md`

Each file has one responsibility. `lab/` files are small (<200 lines each). Each experiment is one file that a reader can absorb top-to-bottom without jumping.

---

## Task 0: Bootstrap — git, venv, structure, deps

**Files:**
- Create: `.gitignore`, `requirements.txt`, `pytest.ini`, `lab/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Init git and directory skeleton**

```bash
cd /home/kkopec/projects/multi-procces-thread-acync
git init
mkdir -p lab experiments pitfalls tests results tmp_data
```

- [ ] **Step 2: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
results/
tmp_data/
.DS_Store
*.egg-info/
```

- [ ] **Step 3: Write `requirements.txt`**

```
httpx==0.27.2
aiofiles==24.1.0
aiohttp==3.10.10
psutil==6.1.0
matplotlib==3.9.2
pytest==8.3.3
pytest-asyncio==0.24.0
respx==0.21.1
```

(`pytest-asyncio` for async test support; `respx` for mocking httpx in `test_workloads.py`.)

- [ ] **Step 4: Write `pytest.ini`**

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
addopts = -v --tb=short
```

- [ ] **Step 5: Create empty package markers**

`lab/__init__.py`:
```python
"""Concurrency laboratory — shared engine for concurrency experiments."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 6: Write `tests/conftest.py` with shared fixtures**

```python
"""Shared pytest fixtures."""
from pathlib import Path

import pytest


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    """A temporary CSV path that does not exist yet."""
    return tmp_path / "metrics.csv"
```

- [ ] **Step 7: Install dependencies**

Run: `.venv/bin/pip install -r requirements.txt`
Expected: all packages install without error.

- [ ] **Step 8: Verify pytest finds zero tests and succeeds**

Run: `.venv/bin/pytest`
Expected: `no tests ran` with exit code 5 (acceptable for empty suite) — rerun with `.venv/bin/pytest --collect-only` to confirm no collection errors.

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements.txt pytest.ini lab/ tests/
git commit -m "chore: bootstrap concurrency lab skeleton"
```

---

## Task 1: `lab/metrics.py` — dataclass + CSV persistence

**Files:**
- Create: `lab/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing test for `Metrics` construction**

`tests/test_metrics.py`:
```python
"""Tests for lab.metrics."""
from pathlib import Path

import pytest

from lab.metrics import Metrics, append_csv, load_csv


def test_metrics_defaults_to_empty_extra():
    m = Metrics(
        experiment="01_cpu_primes",
        paradigm="threading",
        workers=4,
        n_tasks=4,
        duration_s=1.23,
        cpu_percent_avg=312.5,
        mem_mb_peak=180.0,
    )
    assert m.extra == {}
    assert m.paradigm == "threading"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_metrics.py::test_metrics_defaults_to_empty_extra -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lab.metrics'`.

- [ ] **Step 3: Implement `Metrics` dataclass**

`lab/metrics.py`:
```python
"""Metrics dataclass and CSV persistence for concurrency experiments."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Metrics:
    experiment: str
    paradigm: str
    workers: int
    n_tasks: int
    duration_s: float
    cpu_percent_avg: float
    mem_mb_peak: float
    extra: dict = field(default_factory=dict)


_CSV_COLUMNS = [
    "experiment",
    "paradigm",
    "workers",
    "n_tasks",
    "duration_s",
    "cpu_percent_avg",
    "mem_mb_peak",
    "extra_json",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_metrics.py::test_metrics_defaults_to_empty_extra -v`
Expected: PASS.

- [ ] **Step 5: Write failing test for `append_csv` + `load_csv` round-trip**

Append to `tests/test_metrics.py`:
```python
def test_append_csv_creates_file_with_header(tmp_csv: Path):
    m = Metrics("e", "threading", 4, 4, 1.0, 300.0, 50.0, {"payload": 1024})
    append_csv(tmp_csv, m)

    assert tmp_csv.exists()
    text = tmp_csv.read_text()
    assert text.startswith("experiment,paradigm,workers,n_tasks,duration_s,cpu_percent_avg,mem_mb_peak,extra_json\n")
    assert '"payload": 1024' in text or '"payload":1024' in text


def test_load_csv_roundtrip_preserves_extra(tmp_csv: Path):
    original = Metrics("e", "asyncio", 100, 100, 0.5, 45.0, 80.0, {"n_urls": 100})
    append_csv(tmp_csv, original)

    rows = load_csv(tmp_csv)

    assert len(rows) == 1
    assert rows[0] == original


def test_append_preserves_previous_rows(tmp_csv: Path):
    first = Metrics("e", "threading", 4, 4, 1.0, 300.0, 50.0, {})
    second = Metrics("e", "multiprocessing", 4, 4, 0.3, 380.0, 200.0, {})
    append_csv(tmp_csv, first)
    append_csv(tmp_csv, second)

    rows = load_csv(tmp_csv)

    assert len(rows) == 2
    assert rows[0].paradigm == "threading"
    assert rows[1].paradigm == "multiprocessing"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: FAIL — `ImportError: cannot import name 'append_csv'`.

- [ ] **Step 7: Implement `append_csv` and `load_csv`**

Append to `lab/metrics.py`:
```python
def append_csv(path: Path, m: Metrics) -> None:
    """Append a Metrics row to CSV at `path`, writing header if file is new."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(_CSV_COLUMNS)
        writer.writerow([
            m.experiment,
            m.paradigm,
            m.workers,
            m.n_tasks,
            f"{m.duration_s:.6f}",
            f"{m.cpu_percent_avg:.3f}",
            f"{m.mem_mb_peak:.3f}",
            json.dumps(m.extra, sort_keys=True),
        ])


def load_csv(path: Path) -> list[Metrics]:
    """Load Metrics rows from a CSV written by append_csv."""
    path = Path(path)
    rows: list[Metrics] = []
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                Metrics(
                    experiment=row["experiment"],
                    paradigm=row["paradigm"],
                    workers=int(row["workers"]),
                    n_tasks=int(row["n_tasks"]),
                    duration_s=float(row["duration_s"]),
                    cpu_percent_avg=float(row["cpu_percent_avg"]),
                    mem_mb_peak=float(row["mem_mb_peak"]),
                    extra=json.loads(row["extra_json"]) if row["extra_json"] else {},
                )
            )
    return rows
```

- [ ] **Step 8: Run all metrics tests, verify all pass**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
git add lab/metrics.py tests/test_metrics.py
git commit -m "feat(lab): Metrics dataclass with CSV round-trip"
```

---

## Task 2: `lab/workloads.py` — pure paradigm-agnostic functions

**Files:**
- Create: `lab/workloads.py`
- Test: `tests/test_workloads.py`

- [ ] **Step 1: Write failing tests for CPU workloads**

`tests/test_workloads.py`:
```python
"""Tests for lab.workloads."""
from pathlib import Path

import httpx
import pytest
import respx

from lab.workloads import (
    count_primes_up_to,
    fetch_url_async,
    fetch_url_sync,
    hash_bytes,
    is_prime,
    read_file_async,
    read_file_sync,
)


def test_is_prime_handles_edge_cases():
    assert is_prime(2) is True
    assert is_prime(3) is True
    assert is_prime(4) is False
    assert is_prime(1) is False
    assert is_prime(0) is False
    assert is_prime(-5) is False


def test_count_primes_up_to_matches_known_counts():
    # π(10) = 4  (2, 3, 5, 7)
    assert count_primes_up_to(10) == 4
    # π(100) = 25
    assert count_primes_up_to(100) == 25


def test_hash_bytes_is_deterministic():
    data = b"hello world" * 1000
    assert hash_bytes(data, rounds=1) == hash_bytes(data, rounds=1)


def test_hash_bytes_rounds_change_output():
    data = b"xyz"
    assert hash_bytes(data, rounds=1) != hash_bytes(data, rounds=5)
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_workloads.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement CPU workloads**

`lab/workloads.py`:
```python
"""Pure, paradigm-agnostic workload functions used by experiments."""
from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
import httpx


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def count_primes_up_to(limit: int) -> int:
    """CPU-bound workload: count primes in [2, limit]."""
    return sum(1 for n in range(2, limit + 1) if is_prime(n))


def hash_bytes(data: bytes, rounds: int) -> str:
    """CPU-bound workload: repeatedly hash `data` `rounds` times."""
    digest = data
    for _ in range(rounds):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()
```

- [ ] **Step 4: Run CPU workload tests, verify passing**

Run: `.venv/bin/pytest tests/test_workloads.py -k "prime or hash" -v`
Expected: 4 passed.

- [ ] **Step 5: Write failing tests for HTTP workloads**

Append to `tests/test_workloads.py`:
```python
@respx.mock
def test_fetch_url_sync_returns_body_length():
    respx.get("http://example.test/foo").respond(200, text="hello")
    with httpx.Client() as client:
        length = fetch_url_sync(client, "http://example.test/foo")
    assert length == 5


@pytest.mark.asyncio
@respx.mock
async def test_fetch_url_async_returns_body_length():
    respx.get("http://example.test/bar").respond(200, text="hello world")
    async with httpx.AsyncClient() as client:
        length = await fetch_url_async(client, "http://example.test/bar")
    assert length == 11
```

- [ ] **Step 6: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_workloads.py -k "fetch" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 7: Implement HTTP workloads**

Append to `lab/workloads.py`:
```python
def fetch_url_sync(client: httpx.Client, url: str) -> int:
    """I/O workload: blocking HTTP GET, returns response body length."""
    response = client.get(url)
    response.raise_for_status()
    return len(response.content)


async def fetch_url_async(client: httpx.AsyncClient, url: str) -> int:
    """I/O workload: async HTTP GET, returns response body length."""
    response = await client.get(url)
    response.raise_for_status()
    return len(response.content)
```

- [ ] **Step 8: Run HTTP tests, verify passing**

Run: `.venv/bin/pytest tests/test_workloads.py -k "fetch" -v`
Expected: 2 passed.

- [ ] **Step 9: Write failing tests for file workloads**

Append to `tests/test_workloads.py`:
```python
def test_read_file_sync_returns_byte_count(tmp_path: Path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"x" * 1024)
    assert read_file_sync(p) == 1024


@pytest.mark.asyncio
async def test_read_file_async_returns_byte_count(tmp_path: Path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"y" * 2048)
    assert await read_file_async(p) == 2048
```

- [ ] **Step 10: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_workloads.py -k "read_file" -v`
Expected: FAIL.

- [ ] **Step 11: Implement file workloads**

Append to `lab/workloads.py`:
```python
def read_file_sync(path: Path) -> int:
    """I/O workload: blocking file read, returns byte count."""
    with Path(path).open("rb") as f:
        return len(f.read())


async def read_file_async(path: Path) -> int:
    """I/O workload: async file read via aiofiles, returns byte count."""
    async with aiofiles.open(path, "rb") as f:
        data = await f.read()
    return len(data)
```

- [ ] **Step 12: Run all workloads tests, verify passing**

Run: `.venv/bin/pytest tests/test_workloads.py -v`
Expected: 8 passed.

- [ ] **Step 13: Commit**

```bash
git add lab/workloads.py tests/test_workloads.py
git commit -m "feat(lab): paradigm-agnostic workload functions"
```

---

## Task 3: `lab/runner.py` — basic timing + coroutine detection + exception capture

**Files:**
- Create: `lab/runner.py`
- Test: `tests/test_runner.py`

This task lands the non-psutil parts of the runner. Sampling is added in Task 4; repeats in Task 5. Kept separate so each layer has its own tests and commit.

- [ ] **Step 1: Write failing tests for basic timing**

`tests/test_runner.py`:
```python
"""Tests for lab.runner."""
import asyncio
import time
from pathlib import Path

import pytest

from lab.metrics import load_csv
from lab.runner import measure


def _sleep_sync(duration: float, **_):
    time.sleep(duration)


async def _sleep_async(duration: float, **_):
    await asyncio.sleep(duration)


def test_measure_sync_reports_positive_duration():
    m = measure(
        experiment="t",
        paradigm="sequential",
        fn=_sleep_sync,
        workers=1,
        n_tasks=1,
        duration=0.1,
    )
    assert m.duration_s >= 0.09
    assert m.duration_s < 0.5


def test_measure_detects_coroutine_function():
    m = measure(
        experiment="t",
        paradigm="asyncio",
        fn=_sleep_async,
        workers=1,
        n_tasks=1,
        duration=0.1,
    )
    assert m.duration_s >= 0.09


def test_measure_appends_to_csv(tmp_csv: Path):
    measure(
        experiment="t",
        paradigm="sequential",
        fn=_sleep_sync,
        workers=1,
        n_tasks=1,
        csv_path=tmp_csv,
        duration=0.01,
    )
    rows = load_csv(tmp_csv)
    assert len(rows) == 1
    assert rows[0].paradigm == "sequential"


def _raiser(**_):
    raise RuntimeError("boom")


def test_measure_records_failure_without_raising(tmp_csv: Path):
    m = measure(
        experiment="t",
        paradigm="threading",
        fn=_raiser,
        workers=1,
        n_tasks=1,
        csv_path=tmp_csv,
    )
    assert m.duration_s == -1.0
    assert "boom" in m.extra["error"]
    rows = load_csv(tmp_csv)
    assert len(rows) == 1
    assert rows[0].duration_s == -1.0
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: FAIL — `lab.runner` not found.

- [ ] **Step 3: Implement minimal `measure()` (no sampling yet)**

`lab/runner.py`:
```python
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
```

- [ ] **Step 4: Run tests, verify passing**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lab/runner.py tests/test_runner.py
git commit -m "feat(lab): runner with timing, coroutine detection, failure capture"
```

---

## Task 4: `lab/runner.py` — psutil sampler with child-process aggregation

Spec §5.2.1: CPU% and memory must aggregate across parent + live children, or multiprocessing will falsely report near-zero CPU.

**Files:**
- Modify: `lab/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing test for non-zero CPU in busy loop**

Append to `tests/test_runner.py`:
```python
def _burn_cpu(iterations: int, **_):
    n = 0
    for i in range(iterations):
        n += i * i
    return n


def test_measure_reports_nonzero_cpu_for_busy_loop():
    m = measure(
        experiment="t",
        paradigm="sequential",
        fn=_burn_cpu,
        workers=1,
        n_tasks=1,
        iterations=5_000_000,
    )
    assert m.cpu_percent_avg > 10.0, f"CPU too low: {m.cpu_percent_avg}"
    assert m.mem_mb_peak > 0.0
```

- [ ] **Step 2: Write failing test for multiprocessing aggregation**

Append to `tests/test_runner.py`:
```python
from concurrent.futures import ProcessPoolExecutor


def _mp_burn(iterations: int, **_):
    # Top-level so the Pool can pickle it.
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(_burn_cpu_pool, [iterations] * 4))


def _burn_cpu_pool(iterations):
    n = 0
    for i in range(iterations):
        n += i * i
    return n


def test_measure_aggregates_child_processes():
    m = measure(
        experiment="t",
        paradigm="multiprocessing",
        fn=_mp_burn,
        workers=4,
        n_tasks=4,
        iterations=2_000_000,
    )
    # With 4 children each near 100%, aggregate should comfortably exceed 100%.
    assert m.cpu_percent_avg > 100.0, f"Expected aggregate >100%, got {m.cpu_percent_avg}"
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_runner.py -k "busy or aggregates" -v`
Expected: FAIL — `cpu_percent_avg` is 0.

- [ ] **Step 4: Replace `measure()` with sampled version**

Replace `lab/runner.py` entirely:
```python
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
        self._primed: set[int] = set()
        self._cpu_samples: list[float] = []
        self._mem_peak_mb = 0.0

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
        procs = [self._parent]
        try:
            procs.extend(self._parent.children(recursive=True))
        except psutil.NoSuchProcess:
            return 0.0, 0.0

        cpu_total = 0.0
        mem_total_mb = 0.0
        for proc in procs:
            try:
                if proc.pid not in self._primed:
                    self._prime(proc)
                    continue  # first call always returns 0; skip this sample
                cpu_total += proc.cpu_percent(interval=None)
                mem_total_mb += proc.memory_info().rss / (1024 * 1024)
            except psutil.NoSuchProcess:
                self._primed.discard(proc.pid)
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

    CPU% and mem_mb_peak are aggregates across parent + live child processes.

    NOTE: If fn is async, any httpx.AsyncClient / aiohttp.ClientSession must be
    constructed INSIDE fn — each call gets a fresh event loop via asyncio.run().
    """
    is_coro = inspect.iscoroutinefunction(fn)
    extra: dict = {}

    sampler = _Sampler(sample_interval_s)
    sampler.start()
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
    cpu_avg, mem_peak = sampler.stop()

    m = Metrics(
        experiment=experiment,
        paradigm=paradigm,
        workers=workers,
        n_tasks=n_tasks,
        duration_s=duration,
        cpu_percent_avg=cpu_avg,
        mem_mb_peak=mem_peak,
        extra=extra,
    )
    if csv_path is not None:
        append_csv(csv_path, m)
    return m
```

- [ ] **Step 5: Run all runner tests, verify passing**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: 6 passed. `test_measure_aggregates_child_processes` may take 5-10s.

- [ ] **Step 6: Commit**

```bash
git add lab/runner.py tests/test_runner.py
git commit -m "feat(lab): psutil sampler with parent+children aggregation"
```

---

## Task 5: `lab/runner.py` — n_repeats, warmup, median

Spec §8.1: single-shot variance is 5-15%; need repeats + median to meet success criterion §13.4.

**Files:**
- Modify: `lab/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing tests for repeats**

Append to `tests/test_runner.py`:
```python
def test_measure_n_repeats_writes_all_rows(tmp_csv: Path):
    m = measure(
        experiment="t",
        paradigm="sequential",
        fn=_sleep_sync,
        workers=1,
        n_tasks=1,
        csv_path=tmp_csv,
        n_repeats=3,
        duration=0.01,
    )
    rows = load_csv(tmp_csv)
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"
    repeat_indices = sorted(r.extra["repeat_idx"] for r in rows)
    assert repeat_indices == [0, 1, 2]
    # Returned Metrics is the median (one of the written rows).
    assert m.duration_s in {r.duration_s for r in rows}


def test_measure_warmup_not_written_to_csv(tmp_csv: Path):
    measure(
        experiment="t",
        paradigm="sequential",
        fn=_sleep_sync,
        workers=1,
        n_tasks=1,
        csv_path=tmp_csv,
        n_repeats=2,
        warmup=True,
        duration=0.01,
    )
    rows = load_csv(tmp_csv)
    assert len(rows) == 2  # warmup excluded
    assert all("warmup" not in r.extra for r in rows)


def test_measure_returns_median_duration():
    # 5 repeats with deterministic increasing sleeps would be flaky; just assert
    # that returned duration is one of the per-run durations (median semantics).
    m = measure(
        experiment="t",
        paradigm="sequential",
        fn=_sleep_sync,
        workers=1,
        n_tasks=1,
        n_repeats=5,
        duration=0.02,
    )
    assert m.duration_s >= 0.015
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_runner.py -k "repeats or warmup or median" -v`
Expected: FAIL — `n_repeats` not a parameter yet.

- [ ] **Step 3: Refactor `measure()` — extract single-run, add repeats/warmup/median**

Replace the `measure` function in `lab/runner.py` (keep `_Sampler` as-is):
```python
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
        duration = time.perf_counter() - start
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
```

- [ ] **Step 4: Run runner tests, verify passing**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add lab/runner.py tests/test_runner.py
git commit -m "feat(lab): n_repeats, warmup, and median selection in runner"
```

---

## Task 6: `lab/plot.py` — bar and line charts

**Files:**
- Create: `lab/plot.py`
- Test: `tests/test_plot.py`

- [ ] **Step 1: Write failing smoke tests**

`tests/test_plot.py`:
```python
"""Smoke tests for lab.plot (no visual assertions)."""
from pathlib import Path

from lab.metrics import Metrics, append_csv
from lab.plot import compare_bar, scaling_line


def _seed_compare_csv(path: Path) -> None:
    rows = [
        Metrics("e", "sequential", 1, 4, 4.0, 100.0, 30.0, {"repeat_idx": 0}),
        Metrics("e", "threading", 4, 4, 4.1, 110.0, 32.0, {"repeat_idx": 0}),
        Metrics("e", "multiprocessing", 4, 4, 1.1, 380.0, 180.0, {"repeat_idx": 0}),
        Metrics("e", "asyncio", 4, 4, 4.0, 100.0, 30.0, {"repeat_idx": 0}),
    ]
    for m in rows:
        append_csv(path, m)


def _seed_scaling_csv(path: Path) -> None:
    for workers in (1, 2, 4, 8):
        append_csv(path, Metrics("e", "threading", workers, workers, 4.0, 100.0, 30.0, {}))
        append_csv(path, Metrics("e", "multiprocessing", workers, workers, 4.0 / workers, 400.0, 200.0, {}))
        append_csv(path, Metrics("e", "asyncio", workers, workers, 4.0, 100.0, 30.0, {}))


def test_compare_bar_produces_png(tmp_path: Path):
    csv = tmp_path / "m.csv"
    out = tmp_path / "m.png"
    _seed_compare_csv(csv)
    compare_bar(csv, out, metric="duration_s")
    assert out.exists()
    assert out.stat().st_size > 0


def test_scaling_line_produces_png(tmp_path: Path):
    csv = tmp_path / "m.csv"
    out = tmp_path / "m.png"
    _seed_scaling_csv(csv)
    scaling_line(csv, out)
    assert out.exists()
    assert out.stat().st_size > 0
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/pytest tests/test_plot.py -v`
Expected: FAIL — `lab.plot` not found.

- [ ] **Step 3: Implement `lab/plot.py`**

```python
"""Matplotlib plots comparing paradigms across experiments.

Each chart reads a CSV produced by runner.measure() and writes a PNG.
Machine identity (CPU model, core count, Python version) is embedded in the
figure subtitle so saved images remain interpretable in isolation.
"""
from __future__ import annotations

import os
import platform
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend for CI / servers
import matplotlib.pyplot as plt

from lab.metrics import Metrics, load_csv

_PARADIGM_ORDER = ["sequential", "threading", "multiprocessing", "asyncio"]
_PARADIGM_COLORS = {
    "sequential": "#888888",
    "threading": "#1f77b4",
    "multiprocessing": "#d62728",
    "asyncio": "#2ca02c",
}


def _machine_label() -> str:
    return (
        f"{platform.processor() or 'unknown CPU'} · "
        f"{os.cpu_count()} cores · Python {sys.version_info.major}.{sys.version_info.minor}"
    )


def _group_by_paradigm(rows: list[Metrics]) -> dict[str, list[Metrics]]:
    grouped: dict[str, list[Metrics]] = defaultdict(list)
    for r in rows:
        grouped[r.paradigm].append(r)
    return grouped


def _median_row(rows: list[Metrics]) -> Metrics:
    by_duration = sorted(rows, key=lambda m: m.duration_s)
    return by_duration[len(by_duration) // 2]


def compare_bar(csv_path: Path, out_path: Path, metric: str = "duration_s") -> None:
    """Bar chart: one bar per paradigm (median across repeats)."""
    rows = load_csv(csv_path)
    if not rows:
        raise ValueError(f"No rows in {csv_path}")

    experiment = rows[0].experiment
    grouped = _group_by_paradigm(rows)
    paradigms = [p for p in _PARADIGM_ORDER if p in grouped]

    medians: list[float] = []
    mins: list[float] = []
    maxes: list[float] = []
    for p in paradigms:
        values = [getattr(r, metric) for r in grouped[p] if r.duration_s >= 0]
        if not values:
            medians.append(0.0); mins.append(0.0); maxes.append(0.0)
            continue
        medians.append(statistics.median(values))
        mins.append(min(values))
        maxes.append(max(values))

    errors = [
        [m - lo for m, lo in zip(medians, mins)],
        [hi - m for m, hi in zip(medians, maxes)],
    ]
    colors = [_PARADIGM_COLORS.get(p, "#777") for p in paradigms]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(paradigms, medians, color=colors, yerr=errors, capsize=6)
    ax.set_ylabel(metric)
    ax.set_title(f"{experiment} — {metric} by paradigm")
    fig.suptitle(_machine_label(), fontsize=8, y=0.01)
    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def scaling_line(csv_path: Path, out_path: Path) -> None:
    """Line chart: x = workers, y = duration_s (median), one line per paradigm."""
    rows = load_csv(csv_path)
    if not rows:
        raise ValueError(f"No rows in {csv_path}")

    experiment = rows[0].experiment
    grouped: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.duration_s < 0:
            continue
        grouped[r.paradigm][r.workers].append(r.duration_s)

    fig, ax = plt.subplots(figsize=(9, 5))
    for paradigm in _PARADIGM_ORDER:
        if paradigm not in grouped:
            continue
        workers_axis = sorted(grouped[paradigm].keys())
        medians = [statistics.median(grouped[paradigm][w]) for w in workers_axis]
        lows = [min(grouped[paradigm][w]) for w in workers_axis]
        highs = [max(grouped[paradigm][w]) for w in workers_axis]
        color = _PARADIGM_COLORS.get(paradigm, "#777")
        ax.plot(workers_axis, medians, "o-", label=paradigm, color=color)
        ax.fill_between(workers_axis, lows, highs, color=color, alpha=0.15)

    ax.set_xlabel("workers")
    ax.set_ylabel("duration_s (median, shaded = min/max)")
    ax.set_xscale("log", base=2)
    ax.set_title(f"{experiment} — scaling")
    ax.legend()
    fig.suptitle(_machine_label(), fontsize=8, y=0.01)
    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
```

- [ ] **Step 4: Run plot tests, verify passing**

Run: `.venv/bin/pytest tests/test_plot.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add lab/plot.py tests/test_plot.py
git commit -m "feat(lab): matplotlib compare_bar and scaling_line"
```

---

## Task 7: Experiment 01 — CPU-bound primes (end-to-end validation)

**Files:**
- Create: `experiments/01_cpu_primes.py`

- [ ] **Step 1: Write experiment**

```python
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
```

- [ ] **Step 2: Run experiment end-to-end**

Run: `.venv/bin/python experiments/01_cpu_primes.py`
Expected: Four paradigm results printed; `results/01_cpu_primes.csv` and `results/01_cpu_primes.png` created. Total runtime: 1-3 min depending on hardware.

Expected qualitative shape:
- sequential: T seconds
- threading: ≈ T or slightly slower (GIL)
- multiprocessing: T / min(WORKERS, cpu_count) — significantly faster
- asyncio: ≈ T (to_thread still GIL-bound for CPU)

- [ ] **Step 3: Commit**

```bash
git add experiments/01_cpu_primes.py
git commit -m "feat(exp): 01_cpu_primes — GIL kills threading for CPU work"
```

---

## Task 8: `lab/mock_server.py` — local aiohttp server for network experiments

**Files:**
- Create: `lab/mock_server.py`

- [ ] **Step 1: Write mock server**

```python
"""Local aiohttp server for deterministic network experiments.

Exposes:
    GET /delay/{seconds}   — sleeps N seconds, returns {"ok": true}
    GET /payload/{bytes}   — returns N random bytes (seeded once, then cached)

Usage:
    with MockServer() as server:
        base = server.base_url
        # spawn workers against base + "/delay/1" etc.
"""
from __future__ import annotations

import asyncio
import random
import socket
import threading
from typing import Optional

from aiohttp import web


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_payload_cache() -> dict[int, bytes]:
    # Deterministic payloads for reproducibility.
    rng = random.Random(42)
    cache: dict[int, bytes] = {}
    for size in (1_000, 10_000, 50_000, 100_000, 1_000_000):
        cache[size] = bytes(rng.randrange(256) for _ in range(size))
    return cache


class MockServer:
    def __init__(self, port: Optional[int] = None):
        self.port = port or _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._runner: Optional[web.AppRunner] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_request: Optional[asyncio.Future] = None
        self._payload_cache = _build_payload_cache()

    async def _handle_delay(self, request: web.Request) -> web.Response:
        seconds = float(request.match_info["seconds"])
        await asyncio.sleep(seconds)
        return web.json_response({"ok": True, "slept": seconds})

    async def _handle_payload(self, request: web.Request) -> web.Response:
        size = int(request.match_info["bytes"])
        data = self._payload_cache.get(size)
        if data is None:
            # On-demand, still deterministic per-size via seed(size).
            rng = random.Random(size)
            data = bytes(rng.randrange(256) for _ in range(size))
            self._payload_cache[size] = data
        return web.Response(body=data, content_type="application/octet-stream")

    async def _serve(self) -> None:
        app = web.Application()
        app.router.add_get("/delay/{seconds}", self._handle_delay)
        app.router.add_get("/payload/{bytes}", self._handle_payload)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await site.start()
        self._ready.set()

        self._stop_request = asyncio.get_running_loop().create_future()
        try:
            await self._stop_request
        finally:
            await self._runner.cleanup()

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    def __enter__(self) -> "MockServer":
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("MockServer failed to start within 5 seconds")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._loop and self._stop_request and not self._stop_request.done():
            self._loop.call_soon_threadsafe(self._stop_request.set_result, None)
        if self._thread:
            self._thread.join(timeout=5.0)


if __name__ == "__main__":
    import time
    with MockServer() as server:
        print(f"MockServer running at {server.base_url}")
        print("Try: curl http://127.0.0.1:{port}/delay/1".replace("{port}", str(server.port)))
        time.sleep(30)
```

- [ ] **Step 2: Smoke-test the server manually**

Run in one terminal: `.venv/bin/python -m lab.mock_server`
Run in another: `curl http://127.0.0.1:<PORT>/delay/0.5` and `curl -s http://127.0.0.1:<PORT>/payload/1000 | wc -c`
Expected: JSON `{"ok": true, "slept": 0.5}` after ~0.5s; second command prints `1000`.

- [ ] **Step 3: Commit**

```bash
git add lab/mock_server.py
git commit -m "feat(lab): local aiohttp mock server for network experiments"
```

---

## Task 9: Experiment 02 — HTTP fan-out (asyncio dominates)

**Files:**
- Create: `experiments/02_io_http.py`

- [ ] **Step 1: Write experiment**

```python
"""Experiment 02 — asyncio dominates HTTP I/O.

Hypothesis:
    asyncio ≥ threading >> multiprocessing >> sequential for N network requests
    when each request mostly waits on the server.
"""
from __future__ import annotations

import argparse
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


def _fetch_worker(url: str) -> int:
    # Top-level so ProcessPoolExecutor can pickle it.
    with httpx.Client(timeout=30) as client:
        return fetch_url_sync(client, url)


def run_threading(workers: int, **_):
    with httpx.Client(timeout=30) as client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda u: fetch_url_sync(client, u), [_url()] * N_REQUESTS))


def run_multiprocessing(workers: int, **_):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_fetch_worker, [_url()] * N_REQUESTS))


async def run_asyncio(**_):
    # Client MUST be constructed inside the coroutine (fresh event loop per
    # measure() call) — see runner docstring and spec §5.2.
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
        m = measure(
            experiment=EXPERIMENT,
            paradigm=paradigm,
            fn=fn,
            workers=workers,
            n_tasks=N_REQUESTS,
            csv_path=CSV_PATH,
            n_repeats=3,
            warmup=True,
            workers_kw=workers,  # surfaced into params dict for run_* callables
            **{"workers": workers},
        )
        print(f"{m.duration_s:6.2f}s  CPU={m.cpu_percent_avg:5.0f}%  mem={m.mem_mb_peak:5.0f}MB")


if __name__ == "__main__":
    main()
```

**Note on the `workers` double-passing:** `measure()` accepts `workers` as its own parameter (recorded in Metrics) *and* forwards `**params` to `fn`. To let `run_threading(workers=...)` receive it, we also pass `workers=workers` as a kwarg; Python accepts the duplicate because `measure()` consumes its positional `workers` parameter and passes the rest via `**params`. Remove `workers_kw=workers` (vestigial) — corrected below.

- [ ] **Step 2: Correct the kwargs passing — simpler version**

Replace `_run_experiments()` in `experiments/02_io_http.py`:
```python
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
        # accurate without aliasing kwargs.
        import inspect
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
```

- [ ] **Step 3: Run experiment**

Run: `.venv/bin/python experiments/02_io_http.py`
Expected runtime: ~2-3 minutes. Qualitative shape:
- sequential: ~100s
- threading(16): ~7s, threading(64): ~2s
- multiprocessing(16): ~8-15s (process overhead dominates)
- asyncio(100): ~1.5s

- [ ] **Step 4: Commit**

```bash
git add experiments/02_io_http.py
git commit -m "feat(exp): 02_io_http — asyncio dominates HTTP fan-out"
```

---

## Task 10: Experiment 03 — disk I/O with setup/teardown

**Files:**
- Create: `experiments/03_io_disk.py`

- [ ] **Step 1: Write experiment**

```python
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
```

- [ ] **Step 2: Run experiment**

Run: `.venv/bin/python experiments/03_io_disk.py`
Expected: first run does ~30s setup to generate 200 MB in `tmp_data/`; subsequent runs skip setup. Measurements complete in ~30-60s.

- [ ] **Step 3: Commit**

```bash
git add experiments/03_io_disk.py
git commit -m "feat(exp): 03_io_disk — threading/asyncio parity on local disk"
```

---

## Task 11: Experiment 04 — scaling vs worker count (headline chart)

**Files:**
- Create: `experiments/04_scaling.py`

- [ ] **Step 1: Write experiment**

```python
"""Experiment 04 — speedup vs worker count. The headline chart.

Hypothesis:
    threading: flat line (GIL serialises CPU work).
    multiprocessing: descending to ≈ cpu_count, then plateaus (Amdahl).
    asyncio: flat (single thread, to_thread still GIL-bound for CPU).
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
N_TASKS = 16
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
                n_repeats=5,
                warmup=True,
            )
            print(f"{m.duration_s:6.2f}s  CPU={m.cpu_percent_avg:5.0f}%  mem={m.mem_mb_peak:5.0f}MB")

    scaling_line(CSV_PATH, PNG_PATH)
    print(f"\nChart: {PNG_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run experiment**

Run: `.venv/bin/python experiments/04_scaling.py`
Expected runtime: 10-20 min (3 paradigms × 6 worker levels × 5 repeats + warmup). This is the most expensive experiment.

Expected chart shape: three clearly distinct lines matching §13.4 of the spec.

- [ ] **Step 3: Commit**

```bash
git add experiments/04_scaling.py
git commit -m "feat(exp): 04_scaling — headline speedup-vs-workers chart"
```

---

## Task 12: Experiment 05 — mixed workload (hybrid asyncio+executor wins)

**Files:**
- Create: `experiments/05_mixed.py`

- [ ] **Step 1: Write experiment**

```python
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
from lab.workloads import fetch_url_async, fetch_url_sync, hash_bytes

EXPERIMENT = "05_mixed"
N_ITERATIONS = 50
PAYLOAD_BYTES = 50_000
HASH_ROUNDS = 3
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
        data = client.get(_url()).content
    digest = hash_bytes(data, rounds=HASH_ROUNDS)
    (OUT_DIR / f"{i:04d}.txt").write_text(digest)


def _hash_only(data: bytes) -> str:
    return hash_bytes(data, rounds=HASH_ROUNDS)


def run_threading(**_):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_pipeline_step_sync, range(N_ITERATIONS)))


def run_multiprocessing(**_):
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_pipeline_step_sync, range(N_ITERATIONS)))


async def run_asyncio_blocking(**_):
    # Blocking hash_bytes inside the event loop: bad pattern, included to show
    # that "async everywhere" ≠ fast when there's CPU work.
    async with httpx.AsyncClient(timeout=30) as client:
        async def _task(i: int):
            data = (await client.get(_url())).content
            digest = hash_bytes(data, rounds=HASH_ROUNDS)  # blocks loop
            (OUT_DIR / f"{i:04d}.txt").write_text(digest)
        await asyncio.gather(*[_task(i) for i in range(N_ITERATIONS)])


async def run_asyncio_hybrid(**_):
    # Correct pattern: offload CPU to a process pool via run_in_executor.
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        async with httpx.AsyncClient(timeout=30) as client:
            async def _task(i: int):
                data = (await client.get(_url())).content
                digest = await loop.run_in_executor(pool, _hash_only, data)
                (OUT_DIR / f"{i:04d}.txt").write_text(digest)
            await asyncio.gather(*[_task(i) for i in range(N_ITERATIONS)])


def main() -> None:
    global _BASE_URL
    print(f"=== {EXPERIMENT} ===")
    print(f"Python {sys.version.split()[0]} · {platform.processor() or 'unknown CPU'} · {os.cpu_count()} cores")
    print(f"Workload: {N_ITERATIONS} × (fetch {PAYLOAD_BYTES}B → hash×{HASH_ROUNDS} → write)")
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
```

- [ ] **Step 2: Note the label override**

`plot.compare_bar` groups by `paradigm` field; since we want 4 bars (two distinct asyncio variants), we pass custom labels into the `paradigm` argument of `measure()`. The plot's `_PARADIGM_ORDER` only lists canonical names; unknown labels are still rendered (they just fall through the filter in `_group_by_paradigm`). Verify the PNG shows 4 bars after running.

- [ ] **Step 3: Extend `lab/plot.py` to include unknown paradigms in bar charts**

Edit `lab/plot.py`, `compare_bar` function — replace:
```python
    paradigms = [p for p in _PARADIGM_ORDER if p in grouped]
```
with:
```python
    ordered = [p for p in _PARADIGM_ORDER if p in grouped]
    extras = [p for p in grouped if p not in _PARADIGM_ORDER]
    paradigms = ordered + extras
```

Append a test in `tests/test_plot.py`:
```python
def test_compare_bar_includes_unknown_paradigm(tmp_path: Path):
    csv = tmp_path / "m.csv"
    append_csv(csv, Metrics("e", "threading", 4, 4, 1.0, 100.0, 30.0, {}))
    append_csv(csv, Metrics("e", "asyncio + executor", 4, 4, 0.5, 250.0, 40.0, {}))
    out = tmp_path / "m.png"
    compare_bar(csv, out)
    assert out.exists() and out.stat().st_size > 0
```

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest`
Expected: all tests pass.

- [ ] **Step 5: Run experiment**

Run: `.venv/bin/python experiments/05_mixed.py`
Expected runtime: ~2-3 min.

- [ ] **Step 6: Commit**

```bash
git add experiments/05_mixed.py lab/plot.py tests/test_plot.py
git commit -m "feat(exp): 05_mixed — hybrid asyncio+executor beats pure paradigms"
```

---

## Task 13: Pitfall 01 — race condition (broken + fixed)

**Files:**
- Create: `pitfalls/01_race_condition_broken.py`, `pitfalls/01_race_condition_fixed.py`

- [ ] **Step 1: Write `pitfalls/01_race_condition_broken.py`**

```python
"""Pitfall 01 BROKEN — race condition.

Hypothesis: 10 threads × 100_000 increments should produce 1_000_000.
Reality: threads race on `counter += 1` (which is read-modify-write, not atomic),
producing a value < 1_000_000.

Takeaway: any shared-mutable state accessed from multiple threads needs a lock.
"""
from concurrent.futures import ThreadPoolExecutor

THREADS = 10
ITERATIONS = 100_000

counter = 0


def increment_many() -> None:
    global counter
    for _ in range(ITERATIONS):
        counter += 1


def main() -> None:
    global counter
    counter = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for _ in range(THREADS):
            pool.submit(increment_many)

    expected = THREADS * ITERATIONS
    print(f"expected: {expected}")
    print(f"actual:   {counter}")
    lost = expected - counter
    pct = (lost / expected) * 100
    print(f"lost:     {lost} ({pct:.2f}%) — this is the race condition.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `pitfalls/01_race_condition_fixed.py`**

```python
"""Pitfall 01 FIXED — threading.Lock guards the increment.

The lock serialises the read-modify-write sequence so no increment is lost.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

THREADS = 10
ITERATIONS = 100_000

counter = 0
lock = threading.Lock()


def increment_many() -> None:
    global counter
    for _ in range(ITERATIONS):
        with lock:
            counter += 1


def main() -> None:
    global counter
    counter = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for _ in range(THREADS):
            pool.submit(increment_many)

    expected = THREADS * ITERATIONS
    print(f"expected: {expected}")
    print(f"actual:   {counter}")
    assert counter == expected, "Lock must prevent any lost increments"
    print("✅ all increments preserved")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run both**

Run: `.venv/bin/python pitfalls/01_race_condition_broken.py`
Expected: `actual` < `expected`, positive `lost` count.

Run: `.venv/bin/python pitfalls/01_race_condition_fixed.py`
Expected: exact match, "✅ all increments preserved".

- [ ] **Step 4: Commit**

```bash
git add pitfalls/01_race_condition_broken.py pitfalls/01_race_condition_fixed.py
git commit -m "feat(pitfalls): race condition broken/fixed demo"
```

---

## Task 14: Pitfall 02 — deadlock (broken + fixed, with watchdog)

**Files:**
- Create: `pitfalls/02_deadlock_broken.py`, `pitfalls/02_deadlock_fixed.py`

- [ ] **Step 1: Write `pitfalls/02_deadlock_broken.py`**

```python
"""Pitfall 02 BROKEN — deadlock from inconsistent lock order.

Two threads acquire locks in opposite order. Both can block waiting on the
other, causing a deadlock. A threading.Timer watchdog detects the hang and
exits cleanly so the demo does not require Ctrl+C.

Why not signal.alarm? SIGALRM handlers run in the main thread between bytecode
instructions. A thread stuck inside lock.acquire() never yields, so the handler
never fires. threading.Timer + os._exit is the mechanism that works.
"""
import argparse
import os
import sys
import threading
import time

lock_a = threading.Lock()
lock_b = threading.Lock()


def worker_ab(label: str) -> None:
    with lock_a:
        print(f"[{label}] holding A, requesting B...")
        time.sleep(0.1)  # ensure the other thread has time to grab B
        with lock_b:
            print(f"[{label}] got B (should never reach here)")


def worker_ba(label: str) -> None:
    with lock_b:
        print(f"[{label}] holding B, requesting A...")
        time.sleep(0.1)
        with lock_a:
            print(f"[{label}] got A (should never reach here)")


def watchdog(timeout: float) -> None:
    print(f"🔒 DEADLOCK CAUGHT after {timeout:.1f}s — as expected.")
    print("    Both threads are blocked waiting on each other.")
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    timer = threading.Timer(args.timeout, watchdog, args=(args.timeout,))
    timer.daemon = True
    timer.start()

    t1 = threading.Thread(target=worker_ab, args=("T1",))
    t2 = threading.Thread(target=worker_ba, args=("T2",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    timer.cancel()
    print("no deadlock — lucky scheduling?")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `pitfalls/02_deadlock_fixed.py`**

```python
"""Pitfall 02 FIXED — consistent lock order.

Both threads always acquire lock_a before lock_b. No cyclic wait is possible,
so no deadlock can form.
"""
import threading
import time

lock_a = threading.Lock()
lock_b = threading.Lock()


def worker(label: str) -> None:
    with lock_a:
        print(f"[{label}] holding A, requesting B...")
        time.sleep(0.05)
        with lock_b:
            print(f"[{label}] got B, doing work")


def main() -> None:
    t1 = threading.Thread(target=worker, args=("T1",))
    t2 = threading.Thread(target=worker, args=("T2",))
    t1.start(); t2.start()
    t1.join(); t2.join()
    print("✅ no deadlock — both threads used the same lock order")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run both**

Run: `timeout 10 .venv/bin/python pitfalls/02_deadlock_broken.py`
Expected: after ~5s, prints "🔒 DEADLOCK CAUGHT" and exits 0.

Run: `.venv/bin/python pitfalls/02_deadlock_fixed.py`
Expected: completes within ~1s, prints "✅ no deadlock".

- [ ] **Step 4: Commit**

```bash
git add pitfalls/02_deadlock_broken.py pitfalls/02_deadlock_fixed.py
git commit -m "feat(pitfalls): deadlock demo with threading.Timer watchdog"
```

---

## Task 15: Pitfall 03 — GIL demo

**Files:**
- Create: `pitfalls/03_gil_demo.py`

- [ ] **Step 1: Write the demo**

```python
"""Pitfall 03 — the GIL made visible.

Same CPU-bound workload, three ways: sequential, threading(2), threading(4).
If the GIL really blocks parallel Python execution, the threaded runs should
be no faster than sequential (and often slower, due to context-switch overhead).

This is not a broken/fixed pair — the GIL is the lesson itself. The "fix" for
CPU-bound work is multiprocessing (see experiments/01 and 04).
"""
import time
from concurrent.futures import ThreadPoolExecutor

LIMIT = 2_000_000
N_TASKS = 4


def count_primes(limit: int) -> int:
    n = 0
    for i in range(2, limit + 1):
        is_prime = i > 1
        j = 2
        while j * j <= i:
            if i % j == 0:
                is_prime = False
                break
            j += 1
        if is_prime:
            n += 1
    return n


def run(name: str, fn):
    t = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t
    print(f"  {name:<18} {elapsed:6.2f}s")


def main() -> None:
    print("Same CPU workload, 4 tasks:")
    run("sequential", lambda: [count_primes(LIMIT) for _ in range(N_TASKS)])
    for workers in (2, 4, 8):
        def _fn(w=workers):
            with ThreadPoolExecutor(max_workers=w) as pool:
                list(pool.map(count_primes, [LIMIT] * N_TASKS))
        run(f"threading({workers})", _fn)

    print(
        "\nObservation: threading times match (or exceed) sequential — this is the GIL.\n"
        "The CPython interpreter holds a single lock while executing bytecode, so\n"
        "Python-level CPU work cannot actually run in parallel across threads."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python pitfalls/03_gil_demo.py`
Expected: threading times ≈ sequential (within 20%).

- [ ] **Step 3: Commit**

```bash
git add pitfalls/03_gil_demo.py
git commit -m "feat(pitfalls): GIL demo"
```

---

## Task 16: Pitfall 04 — async blocking (broken + fixed)

**Files:**
- Create: `pitfalls/04_async_blocking_broken.py`, `pitfalls/04_async_blocking_fixed.py`

- [ ] **Step 1: Write `pitfalls/04_async_blocking_broken.py`**

```python
"""Pitfall 04 BROKEN — blocking call inside an async function freezes the loop.

Three tasks each "sleep" 1 second. With non-blocking awaits they would complete
in ~1s total. With time.sleep (which does NOT yield control) they complete in
~3s — the event loop is blocked during each call.
"""
import asyncio
import time


async def bad_task(i: int) -> None:
    print(f"  [{i}] start")
    time.sleep(1)  # 🚨 blocks the event loop
    print(f"  [{i}] done")


async def main() -> None:
    t = time.perf_counter()
    await asyncio.gather(*[bad_task(i) for i in range(3)])
    elapsed = time.perf_counter() - t
    print(f"\nelapsed: {elapsed:.2f}s")
    print("Expected ~1s if tasks ran concurrently. ~3s means the loop was blocked.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write `pitfalls/04_async_blocking_fixed.py`**

```python
"""Pitfall 04 FIXED — two valid ways to unblock the loop.

(a) Replace the blocking call with its async equivalent (asyncio.sleep).
(b) If the blocking call is unavoidable (third-party library), push it to a
    thread with asyncio.to_thread.

Both recover the expected ~1s total runtime.
"""
import asyncio
import time


async def fixed_async_sleep(i: int) -> None:
    print(f"  [a/{i}] start")
    await asyncio.sleep(1)
    print(f"  [a/{i}] done")


async def fixed_to_thread(i: int) -> None:
    print(f"  [b/{i}] start")
    await asyncio.to_thread(time.sleep, 1)
    print(f"  [b/{i}] done")


async def run_variant(name: str, coro_factory) -> None:
    print(f"\n--- {name} ---")
    t = time.perf_counter()
    await asyncio.gather(*[coro_factory(i) for i in range(3)])
    print(f"elapsed: {time.perf_counter() - t:.2f}s")


async def main() -> None:
    await run_variant("(a) await asyncio.sleep", fixed_async_sleep)
    await run_variant("(b) await asyncio.to_thread(time.sleep, ...)", fixed_to_thread)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run both**

Run: `.venv/bin/python pitfalls/04_async_blocking_broken.py`
Expected: elapsed ≈ 3s.

Run: `.venv/bin/python pitfalls/04_async_blocking_fixed.py`
Expected: both variants elapsed ≈ 1s.

- [ ] **Step 4: Commit**

```bash
git add pitfalls/04_async_blocking_broken.py pitfalls/04_async_blocking_fixed.py
git commit -m "feat(pitfalls): async blocking call demo"
```

---

## Task 17: Pitfall 05 — pickle error (broken + fixed)

**Files:**
- Create: `pitfalls/05_pickle_broken.py`, `pitfalls/05_pickle_fixed.py`

- [ ] **Step 1: Write `pitfalls/05_pickle_broken.py`**

```python
"""Pitfall 05 BROKEN — multiprocessing cannot pickle lambdas or local functions.

multiprocessing.Pool serialises the target function to send it to worker
processes. Lambdas and nested functions cannot be pickled, so this script
raises PicklingError before any work runs.
"""
from multiprocessing import Pool


def main() -> None:
    # Nested function — also unpicklable.
    def local_double(x: int) -> int:
        return x * 2

    print("Attempting Pool.map with a nested function...")
    try:
        with Pool(processes=2) as pool:
            results = pool.map(local_double, [1, 2, 3])
        print(f"results: {results}  (unexpected — should have raised)")
    except Exception as exc:
        print(f"❌ {type(exc).__name__}: {exc}")

    print("\nAttempting Pool.map with a lambda...")
    try:
        with Pool(processes=2) as pool:
            results = pool.map(lambda x: x * 2, [1, 2, 3])
        print(f"results: {results}")
    except Exception as exc:
        print(f"❌ {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `pitfalls/05_pickle_fixed.py`**

```python
"""Pitfall 05 FIXED — top-level functions pickle cleanly.

Module-level functions are addressable by `module.func_name` at import time,
which is all pickle needs to reconstruct the call on the worker side.
"""
from multiprocessing import Pool


def double(x: int) -> int:
    return x * 2


def main() -> None:
    with Pool(processes=2) as pool:
        results = pool.map(double, [1, 2, 3, 4, 5])
    print(f"results: {results}")
    assert results == [2, 4, 6, 8, 10]
    print("✅ top-level function pickled and executed in child processes")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run both**

Run: `.venv/bin/python pitfalls/05_pickle_broken.py`
Expected: two PicklingError-class errors printed.

Run: `.venv/bin/python pitfalls/05_pickle_fixed.py`
Expected: `results: [2, 4, 6, 8, 10]`.

- [ ] **Step 4: Commit**

```bash
git add pitfalls/05_pickle_broken.py pitfalls/05_pickle_fixed.py
git commit -m "feat(pitfalls): pickle error in multiprocessing demo"
```

---

## Task 18: Pitfall 06 — gather vs TaskGroup

**Files:**
- Create: `pitfalls/06_gather_vs_taskgroup.py`

- [ ] **Step 1: Write the comparison**

```python
"""Pitfall 06 — asyncio.gather vs asyncio.TaskGroup (3.11+).

When one task raises, gather keeps the other tasks running (unless
return_exceptions=False, in which case it re-raises the first error but does
NOT cancel siblings — they run to completion, their results are lost).

TaskGroup, introduced in 3.11, cancels all siblings on the first failure and
raises an ExceptionGroup aggregating every exception raised inside the group.

Run on Python ≥ 3.11.
"""
import asyncio


async def ok(i: int) -> str:
    await asyncio.sleep(0.1)
    return f"ok-{i}"


async def boom(i: int) -> None:
    await asyncio.sleep(0.05)
    raise RuntimeError(f"boom-{i}")


async def gather_demo() -> None:
    print("--- asyncio.gather(return_exceptions=False) ---")
    try:
        results = await asyncio.gather(ok(1), boom(2), ok(3))
        print(f"results: {results}")
    except Exception as exc:
        print(f"caught: {type(exc).__name__}: {exc}")
        # Siblings were NOT cancelled; they completed in the background. We lost their results.

    print("\n--- asyncio.gather(return_exceptions=True) ---")
    results = await asyncio.gather(ok(1), boom(2), ok(3), return_exceptions=True)
    print(f"results: {results}")


async def taskgroup_demo() -> None:
    print("\n--- asyncio.TaskGroup ---")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(ok(1))
            tg.create_task(boom(2))
            tg.create_task(ok(3))
    except* RuntimeError as eg:  # noqa: E999 — except* is 3.11+
        print(f"caught ExceptionGroup with {len(eg.exceptions)} exception(s):")
        for exc in eg.exceptions:
            print(f"  - {type(exc).__name__}: {exc}")


async def main() -> None:
    await gather_demo()
    await taskgroup_demo()
    print(
        "\nTakeaway:\n"
        "  gather: errors don't cancel siblings; return_exceptions=True is a blunt hammer.\n"
        "  TaskGroup: structured concurrency — siblings cancel on failure, errors aggregate."
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python pitfalls/06_gather_vs_taskgroup.py`
Expected: three sections print; final takeaway visible.

- [ ] **Step 3: Commit**

```bash
git add pitfalls/06_gather_vs_taskgroup.py
git commit -m "feat(pitfalls): gather vs TaskGroup comparison"
```

---

## Task 19: Makefile + README + reference results

**Files:**
- Create: `Makefile`, `README.md`
- Create: `docs/reference-results/` (populate from a real run)

- [ ] **Step 1: Write `Makefile`**

```make
.PHONY: install test clean all plots cpu io-http io-disk scaling mixed pitfalls

PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) tests/ -v

cpu:
	$(PYTHON) experiments/01_cpu_primes.py

io-http:
	$(PYTHON) experiments/02_io_http.py

io-disk:
	$(PYTHON) experiments/03_io_disk.py

scaling:
	$(PYTHON) experiments/04_scaling.py

mixed:
	$(PYTHON) experiments/05_mixed.py

all: cpu io-http io-disk scaling mixed

plots:
	@for csv in results/*.csv; do \
		base=$$(basename $$csv .csv); \
		if [ "$$base" = "04_scaling" ]; then \
			$(PYTHON) -c "from pathlib import Path; from lab.plot import scaling_line; scaling_line(Path('$$csv'), Path('results/$$base.png'))"; \
		else \
			$(PYTHON) -c "from pathlib import Path; from lab.plot import compare_bar; compare_bar(Path('$$csv'), Path('results/$$base.png'))"; \
		fi; \
		echo "  regenerated results/$$base.png"; \
	done

pitfalls:
	@for f in pitfalls/*.py; do \
		echo "=== $$f ==="; \
		$(PYTHON) $$f || true; \
		echo; \
	done

clean:
	rm -rf results/* tmp_data/*
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Concurrency Lab — Python threading vs multiprocessing vs asyncio

Hands-on laboratory that proves when each paradigm wins, with real
measurements and matplotlib charts. Companion to `concurrency-pyth-en.md`.

## Setup

```bash
python3 -m venv .venv
make install
make test
```

## Run experiments

```bash
make cpu        # 01 — GIL kills threading for CPU-bound
make io-http    # 02 — asyncio dominates network I/O
make io-disk    # 03 — threading ≈ asyncio on local disk
make scaling    # 04 — headline chart: speedup vs workers
make mixed      # 05 — hybrid asyncio+executor wins
make all        # all five
make plots      # regenerate PNGs from existing CSVs
```

## Experiments

| # | File | Hypothesis | Output |
|---|---|---|---|
| 01 | `experiments/01_cpu_primes.py` | GIL flattens threading for CPU work; multiprocessing ~N×. | `results/01_cpu_primes.png` |
| 02 | `experiments/02_io_http.py` | asyncio ≥ threading >> multiprocessing for 100 HTTP calls. | `results/02_io_http.png` |
| 03 | `experiments/03_io_disk.py` | threading ≈ asyncio for local file I/O; multiprocessing loses. | `results/03_io_disk.png` |
| 04 | `experiments/04_scaling.py` | Three distinct shapes: flat / descending+plateau / flat. | `results/04_scaling.png` |
| 05 | `experiments/05_mixed.py` | For fetch→CPU→write, hybrid asyncio + executor beats pure paradigms. | `results/05_mixed.png` |

## Pitfalls

Each pitfall is a self-contained script that prints its own narrative.

| # | Broken | Fixed | Lesson |
|---|---|---|---|
| 01 | `pitfalls/01_race_condition_broken.py` | `_fixed.py` | Shared mutation needs a `Lock`. |
| 02 | `pitfalls/02_deadlock_broken.py` | `_fixed.py` | Inconsistent lock order → deadlock. Watchdog catches it. |
| 03 | `pitfalls/03_gil_demo.py` | — | Threading does not speed up CPU work. |
| 04 | `pitfalls/04_async_blocking_broken.py` | `_fixed.py` | Sync blocking inside async freezes the loop. |
| 05 | `pitfalls/05_pickle_broken.py` | `_fixed.py` | multiprocessing targets must be picklable. |
| 06 | `pitfalls/06_gather_vs_taskgroup.py` | — | `gather` leaks sibling results on failure; `TaskGroup` cancels + aggregates. |

Run them all with `make pitfalls`.

## Key findings (fill in after first run)

- **CPU-bound (01, 04):** multiprocessing achieved **__×** speedup up to `cpu_count` cores; threading and asyncio stayed within ±5% of sequential.
- **Network I/O (02):** asyncio finished in **__s** vs threading(64) at **__s** vs sequential at ~100s.
- **Disk I/O (03):** threading and asyncio parity (±10%); multiprocessing **__%** slower due to process overhead.
- **Mixed (05):** hybrid asyncio+executor beat pure threading by **__%**.

## How to read the charts

- **Bar charts** — one bar per paradigm, median of N repeats; thin caps show min/max variance.
- **Scaling line chart** — x-axis is worker count (log2); shaded band is min/max across repeats.
- Machine identity (CPU model, core count, Python version) is in each chart's subtitle so saved PNGs stay meaningful.

## Repository layout

```
lab/            # shared engine: runner, metrics, plot, workloads, mock_server
experiments/    # one file per experiment, top-to-bottom readable
pitfalls/       # teaching artefacts (broken/fixed demonstrations)
tests/          # pytest suite for the engine (not the experiments)
results/        # generated CSVs and PNGs (gitignored)
tmp_data/       # generated test files for experiment 03 (gitignored)
docs/           # design spec + implementation plan
```

## References

- `concurrency-pyth-en.md` — theoretical intro (start here if you're new).
- `docs/superpowers/specs/2026-04-17-concurrency-lab-design.md` — design document.
```

- [ ] **Step 3: Run full suite end-to-end to populate reference results**

Run: `make test && make all`
Expected: all tests pass; all five experiments complete and produce PNGs in `results/`.

- [ ] **Step 4: Copy reference results**

```bash
mkdir -p docs/reference-results
cp results/*.csv results/*.png docs/reference-results/
```

- [ ] **Step 5: Fill in README key findings**

Edit `README.md` — replace each `**__×**` / `**__s**` / `**__%**` placeholder with the actual number from the corresponding CSV. Compute from `results/NN.csv` using the median `duration_s` per paradigm.

- [ ] **Step 6: Commit**

```bash
git add Makefile README.md docs/reference-results/
git commit -m "chore: Makefile, README, and reference results"
```

---

## Task 20: Final verification

- [ ] **Step 1: Fresh-clone sanity check**

Run:
```bash
.venv/bin/pytest
```
Expected: all tests pass.

- [ ] **Step 2: Verify the headline chart matches the success criterion**

Open `results/04_scaling.png`. Spec §13.4 requires three visually distinct shapes:
- threading: ~horizontal line
- multiprocessing: descending to cpu_count, then plateau
- asyncio: ~horizontal line

If any line deviates, document the anomaly in README §"Key findings" rather than editing the hypothesis.

- [ ] **Step 3: Verify all pitfalls produce their intended narrative**

Run: `make pitfalls`
Expected: each script prints its hypothesis/observation/takeaway and exits 0 (even broken ones — they catch their own failure and narrate it).

- [ ] **Step 4: Final commit if anything changed**

```bash
git status
git add -A
git commit -m "chore: final verification pass" 2>/dev/null || true
```

---

## Self-review

**Spec coverage check:**
- §2 in-scope items → Tasks 1-18 (5 experiments + 6 pitfalls + engine + tests) ✅
- §3 data flow → Tasks 1, 3-5, 6 ✅
- §5.1 Metrics API → Task 1 ✅
- §5.2 Runner API (timing + sampler + repeats/warmup/median) → Tasks 3, 4, 5 ✅
- §5.2.1 child-process aggregation → Task 4 ✅
- §5.2 async client lifecycle caveat → Documented in runner docstring (Task 3 & 5) and in experiment 02 comment (Task 9) ✅
- §5.3 plot API → Task 6 ✅
- §5.4 workloads → Task 2 ✅
- §5.5 mock server → Task 8 ✅
- §6.1-6.5 experiments → Tasks 7, 9, 10, 11, 12 ✅
- §7 pitfalls 1-6 → Tasks 13-18 ✅
- §8 error handling → Runner exception capture (Task 3), mock server `__exit__` (Task 8), deadlock watchdog (Task 14) ✅
- §8.1 variance handling → Task 5 (n_repeats/median/warmup), Task 6 (error caps/IQR shading) ✅
- §9 testing strategy → Tasks 1, 2, 3, 4, 5, 6, 12 ✅
- §10 dependencies → Task 0 ✅
- §11 Makefile → Task 19 ✅
- §12 implementation order → Tasks 1-19 mirror it ✅
- §13 success criteria → Task 20 ✅

**Placeholder scan:** no "TBD"/"TODO"/"fill in" in code or commands; README has `**__×**`/`**__s**`/`**__%**` placeholders that Task 19 Step 5 explicitly fills in from real measurements. ✅

**Type consistency:** `Metrics` signature is stable from Task 1 onwards; `measure()` signature grows additively in Tasks 3→4→5 (no renames). `paradigm` stays str throughout. ✅

---

**Next step:** execute this plan. See header for execution options.
