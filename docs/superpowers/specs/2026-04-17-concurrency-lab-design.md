# Concurrency Lab — Design Document

**Date:** 2026-04-17
**Author:** kopciu12@gmail.com (brainstormed with Claude)
**Status:** Approved — ready for implementation plan

---

## 1. Purpose

Build a hands-on Python laboratory that **proves on real measurements** when to use
`threading`, `multiprocessing`, and `asyncio`. The lab is an educational companion
to the theory document `concurrency-pyth-en.md` (already in the repository).

The goal is not "a working tool." The goal is **expertise**: each experiment states
a hypothesis, runs three (or four) implementations against it, and produces a chart
that either confirms or refutes the hypothesis. The charts become the "proof" a
learner can point to.

## 2. Scope

### In scope
- 5 experiments covering CPU-bound, I/O-bound (network), I/O-bound (disk), scaling
  vs. worker count, and a mixed workload.
- 6 "pitfall" modules (5 broken/fixed pairs + one comparison): race condition,
  deadlock, GIL, async blocking, pickle errors, `gather` vs `TaskGroup`.
- A minimal shared engine (`lab/`) for measurement, CSV persistence, and plotting.
- Deterministic local HTTP mock server for network experiments (no reliance on
  `httpbin.org`).
- Unit tests for the engine (runner, metrics, workloads, plot smoke test).
- Makefile for convenient CLI runs.

### Out of scope
- Web dashboards, Jupyter notebooks, interactive UIs.
- Packaging as an installable wheel / `pyproject.toml` distribution.
- Testing the experiments or pitfalls themselves — pitfalls are expected to
  crash or hang by design.
- CI pipelines.
- Benchmarks across Python versions or operating systems (results are
  captured from a single machine and annotated with `platform.processor()`).

## 3. High-level architecture

```
experiment.py
     │
     ▼
runner.measure(label, fn, **params)   ──►  Metrics(time, cpu%, mem_mb, label)
     │                                           │
     ▼                                           ▼
results/NN.csv  ◄──── append ───────────────────┘
     │
     ▼
plot.compare(csv_path)  ──►  results/NN.png
```

**Key design principle — separation of workload from paradigm:**
`lab/workloads.py` holds pure, paradigm-agnostic functions (`count_primes_up_to`,
`fetch_url_sync`, etc.). Each experiment wraps the same workload into three
concurrency strategies (`run_threading`, `run_multiprocessing`, `run_asyncio`) and
feeds each strategy through the same `runner.measure()` call. The runner knows
nothing about concurrency paradigms — it receives a `Callable` (or coroutine
function), times it, and records metrics.

**Coroutine handling:** `runner.measure()` detects coroutine functions with
`inspect.iscoroutinefunction(fn)` and wraps the call in `asyncio.run(fn(**params))`.
This keeps experiment code uniform.

## 4. Repository layout

```
concurrency-lab/
├── .venv/                       # gitignored
├── lab/                         # shared engine
│   ├── __init__.py
│   ├── runner.py                # measure() — timing + psutil sampling
│   ├── metrics.py               # Metrics dataclass + CSV append/load
│   ├── plot.py                  # matplotlib bar and line charts
│   ├── workloads.py             # paradigm-agnostic functions
│   └── mock_server.py           # local HTTP server for 02/05
├── experiments/
│   ├── 01_cpu_primes.py
│   ├── 02_io_http.py
│   ├── 03_io_disk.py
│   ├── 04_scaling.py
│   └── 05_mixed.py
├── pitfalls/
│   ├── 01_race_condition_broken.py
│   ├── 01_race_condition_fixed.py
│   ├── 02_deadlock_broken.py
│   ├── 02_deadlock_fixed.py
│   ├── 03_gil_demo.py
│   ├── 04_async_blocking_broken.py
│   ├── 04_async_blocking_fixed.py
│   ├── 05_pickle_broken.py
│   ├── 05_pickle_fixed.py
│   └── 06_gather_vs_taskgroup.py
├── results/                     # gitignored — CSV + PNG outputs
├── tmp_data/                    # gitignored — generated test files for 03
├── tests/
│   ├── test_runner.py
│   ├── test_metrics.py
│   ├── test_workloads.py
│   └── test_plot.py
├── docs/
│   └── superpowers/specs/       # this file lives here
├── requirements.txt
├── Makefile
├── concurrency-pyth-en.md       # theory doc (pre-existing)
└── README.md
```

## 5. Component APIs

### 5.1 `lab/metrics.py`

```python
from dataclasses import dataclass

@dataclass
class Metrics:
    experiment: str       # e.g. "01_cpu_primes"
    paradigm: str         # "sequential" | "threading" | "multiprocessing" | "asyncio"
    workers: int
    n_tasks: int
    duration_s: float
    cpu_percent_avg: float
    mem_mb_peak: float
    extra: dict           # experiment-specific keys (payload_size, url_delay_s, ...)

def append_csv(path: Path, m: Metrics) -> None: ...
def load_csv(path: Path) -> list[Metrics]: ...
```

A runner that fails (the measured function raised) writes a row with
`duration_s = -1.0` and `extra["error"] = "<exception class>: <message>"` so the
CSV stays well-formed and downstream plots can display the failure.

**CSV format:** columns are the flat fields of `Metrics` in declaration order;
`extra` is serialised as a single JSON-encoded string column named `extra_json`
(using `json.dumps(m.extra, sort_keys=True)`). `load_csv` parses it back with
`json.loads`. This keeps the schema stable even as experiments add
paradigm-specific keys.

### 5.2 `lab/runner.py`

```python
def measure(
    experiment: str,
    paradigm: str,
    fn: Callable,                 # sync callable OR coroutine function
    workers: int,
    n_tasks: int,
    csv_path: Path | None = None,
    sample_interval_s: float = 0.05,
    **params,
) -> Metrics:
    """
    Runs fn(**params), sampling CPU% and RSS memory in a background thread at
    sample_interval_s. Returns a Metrics record. Appends to csv_path if given.
    Detects coroutine functions and runs them via asyncio.run().
    """
```

Implementation notes:
- The sampler uses `psutil.Process().cpu_percent(interval=None)` polled at
  `sample_interval_s`; the returned `cpu_percent_avg` is the mean of samples.
- `mem_mb_peak` is `max(sample.memory_info().rss) / 1024 / 1024`.
- The sampler runs in a `threading.Thread` controlled by an `Event`; it adds at
  most ~5% overhead at 50 ms interval, which we accept as the cost of having
  comparable memory/CPU numbers across paradigms.
- Exceptions from `fn` are caught, logged with `traceback.format_exc()`, and
  converted into a failed `Metrics` row (as described above).

#### 5.2.1 Measurement caveats

**CPU% for multiprocessing.** `psutil.Process().cpu_percent()` is *per-process* and
does not aggregate child processes. A naive sampler in the parent would report
near-zero CPU for `multiprocessing` runs, which would silently invalidate
experiments 01, 04, and 05. The sampler therefore:

1. Calls `proc.cpu_percent(interval=None)` once at startup on the parent and on
   every currently-known child to establish the required baseline (the first
   call always returns `0.0`).
2. On each tick, enumerates `parent.children(recursive=True)` and sums
   `cpu_percent()` across parent + live children. New children spawned mid-run
   get their baseline lazily on first sight (their first sample is discarded).
3. Tolerates `psutil.NoSuchProcess` from short-lived workers — dead children
   are dropped from the next tick.

**Memory for multiprocessing.** `mem_mb_peak` is similarly the peak of
`sum(rss for parent + live children)` across samples, not just the parent's
RSS. This is documented as "aggregate RSS" in the CSV column comment so a
reader does not confuse it with per-process memory.

**Async client lifecycle.** Because `runner.measure()` calls `asyncio.run(fn(...))`
on every invocation, each call runs in a fresh event loop. Any
`httpx.AsyncClient` / `aiohttp.ClientSession` **must** be constructed *inside*
`fn` (typically via `async with`), never at module scope. Module-scope clients
bound to a previous loop will raise `RuntimeError: Event loop is closed`. This
constraint is called out in the docstring of `measure()` and in each async
experiment's header comment.

### 5.3 `lab/plot.py`

```python
def compare_bar(csv_path: Path, out_path: Path, metric: str = "duration_s") -> None:
    """
    Bar chart with one bar per paradigm. Used by 01, 02, 03, 05.
    metric ∈ {"duration_s", "cpu_percent_avg", "mem_mb_peak"}.
    """

def scaling_line(csv_path: Path, out_path: Path) -> None:
    """
    Line chart: x = workers, y = duration_s, one line per paradigm.
    Used by 04_scaling. Demonstrates GIL flatline vs. multiprocessing speedup.
    """
```

Each plot writes a PNG and embeds the machine identity (CPU model, core count,
Python version) in the figure subtitle so saved images stay interpretable.

### 5.4 `lab/workloads.py`

Pure functions with no concurrency awareness:

```python
def is_prime(n: int) -> bool: ...
def count_primes_up_to(limit: int) -> int: ...              # CPU-bound
def hash_bytes(data: bytes, rounds: int) -> str: ...        # CPU-bound
def fetch_url_sync(client: httpx.Client, url: str) -> int: ...
async def fetch_url_async(client: httpx.AsyncClient, url: str) -> int: ...
def read_file_sync(path: Path) -> int: ...
async def read_file_async(path: Path) -> int: ...
```

Each returns a deterministic scalar (count, length, digest) to make unit-testing
trivial.

### 5.5 `lab/mock_server.py`

A small `aiohttp.web` app exposing:
- `GET /delay/{seconds}` — sleeps `seconds`, returns `{"ok": true}` JSON.
- `GET /payload/{bytes}` — returns `bytes` random bytes (seeded, cached).

Started on a free port via `aiohttp.web.AppRunner` in a background thread; the
experiment passes the URL to its workers. Ensures zero network flakiness.

## 6. Experiments

### 6.1 `01_cpu_primes.py` — GIL kills threading for CPU work

- **Hypothesis:** For CPU-bound code, `threading ≈ sequential` (often slower),
  `multiprocessing` is ~N× faster up to CPU count, `asyncio ≈ sequential`.
- **Workload:** `count_primes_up_to(2_000_000)` × 4 tasks.
- **Paradigms:** sequential, threading(4), multiprocessing(4), asyncio(4).
- **Output:** `results/01_cpu_primes.csv` + bar chart PNG.

### 6.2 `02_io_http.py` — asyncio dominates network I/O

- **Hypothesis:** `asyncio ≥ threading >> multiprocessing` for large network
  fan-out.
- **Workload:** 100 × `GET /delay/1` against the local mock server.
- **Paradigms:** sequential, threading(4/16/64), multiprocessing(4/16),
  asyncio(100 tasks).
- **Output:** bar chart comparing best variant per paradigm.
- **Flag:** `--external` to target `httpbin.org` instead (optional).

### 6.3 `03_io_disk.py` — disk is the nuanced case

- **Hypothesis:** `threading ≈ asyncio+aiofiles`; `multiprocessing` pays overhead
  with little benefit on local SSD.
- **Workload:** read 200 files × ~1 MB from `tmp_data/`. A `setup()` helper
  generates files once (seeded, cached between runs).
- **Paradigms:** sequential, threading, multiprocessing, asyncio+aiofiles.
- **Output:** bar chart.

### 6.4 `04_scaling.py` — speedup vs. worker count (headline chart)

- **Hypothesis:** threading plateaus (GIL), multiprocessing scales linearly up to
  `os.cpu_count()` then plateaus (Amdahl), asyncio stays flat.
- **Workload:** same CPU-bound task as `01`.
- **Dimension:** workers ∈ {1, 2, 4, 8, 16, 32}.
- **Paradigms:** threading, multiprocessing, asyncio.
- **Output:** line chart, x = workers, y = duration, one line per paradigm.

### 6.5 `05_mixed.py` — realistic combined workload

- **Hypothesis:** For `fetch → CPU hash → write` pipelines, pure threading/mp/
  asyncio all underperform a hybrid (`asyncio` for I/O + `ProcessPoolExecutor`
  for CPU via `loop.run_in_executor`).
- **Workload:** 50 iterations of: fetch `/payload/50000` → `hash_bytes(rounds=3)`
  → write to `results/_mixed_out/`.
- **Paradigms:** threading, multiprocessing, asyncio (blocking hash),
  asyncio+executor (hybrid).
- **Output:** bar chart with 4 bars; the hybrid is expected to win.

## 7. Pitfalls

Each pitfall is a small standalone script that prints its own narrative
(hypothesis, observed behaviour, takeaway). Pitfalls are **not** wired into the
runner/CSV infrastructure — they are teaching artefacts, not measurements.

1. **`01_race_condition`** — 10 threads × 100 000 × `counter += 1`.
   - `broken`: final count < 1 000 000 due to interleaved reads.
   - `fixed`: `threading.Lock` guards the increment.
2. **`02_deadlock`** — two locks taken in opposite order.
   - `broken`: hangs; a `--timeout 5` flag prints "🔒 DEADLOCK CAUGHT" and exits.
   - `fixed`: consistent lock ordering.
3. **`03_gil_demo`** — one-script comparison: threading on CPU work is no faster
   (or slower) than sequential. No "fixed" counterpart; the point is the
   demonstration.
4. **`04_async_blocking`**
   - `broken`: `time.sleep(1)` inside an async function freezes the event loop.
   - `fixed`: `await asyncio.sleep(1)` or `loop.run_in_executor(None, time.sleep, 1)`.
5. **`05_pickle`**
   - `broken`: `Pool.map(lambda x: x * 2, data)` raises `PicklingError`.
   - `fixed`: top-level function.
6. **`06_gather_vs_taskgroup`** — no broken/fixed; one file demonstrates how
   `asyncio.gather` loses sibling cancellation when one task raises, while
   `asyncio.TaskGroup` (3.11+) cancels siblings and aggregates into
   `ExceptionGroup`.

## 8. Error handling and reproducibility

### Error handling
- Runner catches all exceptions from `fn` and records a failed `Metrics` row.
- Deadlock-prone pitfalls use a `--timeout <seconds>` CLI flag (default 5 s).
  Implementation uses `threading.Timer(timeout, watchdog)` started from the
  main thread; `watchdog` prints "🔒 DEADLOCK CAUGHT" and calls `os._exit(0)`.
  `signal.alarm` was rejected because Python signal handlers run only in the
  main thread *and* only between bytecode instructions — a thread blocked
  inside `lock.acquire()` (the actual deadlock state) would never yield, so
  the handler would never fire. `os._exit` is intentional: a normal `sys.exit`
  would also need to wake the deadlocked threads, which is exactly what we
  cannot do.
- Mock server binds to an ephemeral port and is torn down in a `finally` block
  so experiments leave no leaked processes.

### 8.1 Variance handling

Single-shot timing on a developer machine has 5–15% variance from cache,
scheduler, and thermal effects. Without repetition, success criterion §13.4
("three visually distinct shapes") could intermittently fail.

- `runner.measure()` accepts `n_repeats: int = 1`. When > 1, it runs `fn`
  `n_repeats` times back-to-back, records each as a separate CSV row tagged
  with `extra["repeat_idx"]`, and returns the **median** `Metrics` (median
  duration; mean CPU/mem of the median run).
- A single warm-up call is executed before the timed repeats and discarded
  (not written to CSV). It is tagged in logs as `[warmup]`.
- Default `n_repeats` per experiment:
  - `01_cpu_primes`, `04_scaling`: 5 (high signal-to-noise needed for the
    headline charts).
  - `02_io_http`, `03_io_disk`, `05_mixed`: 3.
- Plots use the median row; `compare_bar` overlays min/max as thin error
  caps so variance is visible. `scaling_line` plots median with a shaded
  IQR band.

This is the only place where the runner does anything "smart"; all other
behaviour stays paradigm-agnostic.

### Reproducibility
- `requirements.txt` pins versions.
- Each experiment prints `sys.version`, `platform.processor()`, and
  `os.cpu_count()` at startup.
- Deterministic seed (`random.seed(42)`) for generated data.
- CSV appends across runs; `--clean` flag truncates before writing so users can
  choose accumulation vs. fresh comparison.
- Plots embed machine identity in the subtitle.

## 9. Testing strategy

`tests/` uses `pytest`. We test **infrastructure**, not experiments.

- `test_runner.py` — `measure()` returns positive `duration_s` for trivial sync
  and coroutine functions; reports non-zero CPU for a busy loop; caches
  exceptions as failed rows; detects `async def` via `inspect`.
- `test_metrics.py` — round-trip `Metrics → append_csv → load_csv` preserves all
  fields including `extra`; append preserves earlier rows.
- `test_workloads.py` — `count_primes_up_to(10) == 4`, `hash_bytes` is
  deterministic for identical inputs, `fetch_url_sync` returns the body length
  for a stubbed HTTP response.
- `test_plot.py` — smoke test: given a small CSV, `compare_bar` and
  `scaling_line` produce PNG files > 0 bytes. No visual assertion.

Pitfalls and experiments are **not** unit tested. Pitfalls are meant to misbehave;
experiments are long-running and machine-dependent.

## 10. Dependencies

```
httpx==0.27.2
aiofiles==24.1.0
aiohttp==3.10.10
psutil==6.1.0
matplotlib==3.9.2
pytest==8.3.3
```

## 11. Makefile targets

```make
install   → pip install -r requirements.txt
test      → pytest tests/ -v
cpu       → run experiment 01
io-http   → run experiment 02
io-disk   → run experiment 03
scaling   → run experiment 04
mixed     → run experiment 05
all       → cpu io-http io-disk scaling mixed
plots     → regenerate all PNGs from existing CSVs
pitfalls  → iterate over pitfalls/*.py
clean     → rm results/*, tmp_data/
```

Typical flow: `make install` → `make test` → `make all` → `make plots` → inspect
`results/*.png`.

## 12. Implementation order (recommended for the plan)

1. `lab/metrics.py` + `tests/test_metrics.py`.
2. `lab/workloads.py` + `tests/test_workloads.py`.
3. `lab/runner.py` + `tests/test_runner.py`.
4. `lab/plot.py` + `tests/test_plot.py`.
5. `experiments/01_cpu_primes.py` — first end-to-end validation of the engine.
6. `lab/mock_server.py`.
7. `experiments/02_io_http.py` through `05_mixed.py`.
8. `pitfalls/*` (independent; can be parallelised).
9. `Makefile`, `.gitignore`, `README.md`.
10. Reference run on the author's machine; save representative CSV/PNG to
    `docs/reference-results/` for comparison with future runs.

## 13. Success criteria

The lab is considered successful when:

1. `make test` passes.
2. `make all` completes without manual intervention (mock server lifecycle,
   `tmp_data/` generation, etc. are automatic).
3. Each experiment's `results/NN.png` matches the hypothesis in §6 on the
   author's machine; deviations are documented in README §"Kluczowe wnioski".
4. The `04_scaling.png` chart clearly shows three visually distinct shapes:
   threading flat, multiprocessing descending-then-flat, asyncio flat.
5. Every pitfall prints a short "what happened, why it matters" paragraph, so a
   reader who only runs the script (without reading the code) still learns the
   lesson.

---

**Next step:** invoke `superpowers:writing-plans` to produce the implementation
plan from this design.
