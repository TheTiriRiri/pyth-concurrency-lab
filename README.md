# Concurrency Lab — Python threading vs multiprocessing vs asyncio

Hands-on laboratory that **proves on real measurements** when to use each Python
concurrency paradigm. 5 experiments + 6 pitfall demos + a shared measurement
engine with matplotlib charts. Companion to `_theory/concurrency-pyth-en.md`.

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
make mixed      # 05 — hybrid asyncio+executor matches multiprocessing
make all        # all five
make plots      # regenerate PNGs from existing CSVs
make pitfalls   # run all pitfall scripts
```

## Experiments

| # | File | Hypothesis | Chart |
|---|---|---|---|
| 01 | `experiments/01_cpu_primes.py` | GIL flattens threading for CPU work; multiprocessing ~N×. | `results/01_cpu_primes.png` |
| 02 | `experiments/02_io_http.py` | asyncio ≥ threading >> multiprocessing for HTTP fan-out. | `results/02_io_http.png` |
| 03 | `experiments/03_io_disk.py` | threading ≈ asyncio for local disk I/O; multiprocessing loses. | `results/03_io_disk.png` |
| 04 | `experiments/04_scaling.py` | Three distinct shapes: flat / descending+plateau / flat. | `results/04_scaling.png` |
| 05 | `experiments/05_mixed.py` | For fetch→CPU→write, hybrid asyncio+executor matches multiprocessing. | `results/05_mixed.png` |

## Pitfalls

| # | Broken | Fixed | Lesson |
|---|---|---|---|
| 01 | `pitfalls/01_race_condition_broken.py` | `_fixed.py` | Shared mutation needs a `Lock`. |
| 02 | `pitfalls/02_deadlock_broken.py` | `_fixed.py` | Inconsistent lock order → deadlock. Watchdog catches it via `threading.Timer` + `os._exit`. |
| 03 | `pitfalls/03_gil_demo.py` | — | Threading does not speed up CPU work. |
| 04 | `pitfalls/04_async_blocking_broken.py` | `_fixed.py` | Sync blocking inside async freezes the loop. |
| 05 | `pitfalls/05_pickle_broken.py` | `_fixed.py` | `multiprocessing` targets must be picklable (no lambdas / local functions). |
| 06 | `pitfalls/06_gather_vs_taskgroup.py` | — | `gather` leaks sibling results on failure; `TaskGroup` cancels + aggregates. |

## Measured findings (x86_64 · 20 cores · Python 3.12)

- **01 CPU-bound (4 tasks × count_primes 2M):** sequential 22.0 s → multiprocessing **3.1 s** (~**7× speedup**). Threading and asyncio both stuck at 100 % CPU (one core) due to the GIL.
- **02 Network I/O (100 × delayed GET):** sequential 100.2 s, threading(64) 2.1 s, multiprocessing(16) 7.1 s, **asyncio(100) 1.1 s**. Memory cost makes multiprocessing a bad fit here — 1.2 GB RSS vs ~90 MB for everyone else.
- **03 Local disk I/O (200 × 1 MB files):** sequential 21 ms, threading 60 ms, multiprocessing 75 ms, asyncio 128 ms. On a warm page cache disk is effectively RAM; the "slowest" paradigm is whichever adds the most framework overhead.
- **04 Scaling (headline):** threading and asyncio curves stay near 10–15 s across worker counts; multiprocessing descends 10 s → 2 s, then plateaus at 8 workers (= number of tasks). Three visually distinct shapes — Amdahl vs. GIL side-by-side.
- **05 Mixed (fetch + count_primes):** threading 16 s (GIL on CPU), multiprocessing 1.93 s, asyncio-blocking 10.8 s (CPU blocks the loop), **asyncio + executor 1.89 s**. The hybrid matches multiprocessing with a fraction of the process-per-task overhead.

## Reference results

Snapshot of one run (CSV + PNG) lives in `docs/reference-results/` so you can
compare your machine's behaviour against the numbers above. Your speedups will
differ by core count, RAM bandwidth, and (for experiment 03) whether your disk
cache is warm.

## How to read the charts

- **Bar charts** — one bar per paradigm, median of N repeats; thin caps show min/max across repeats.
- **Scaling line chart (04)** — x-axis is worker count (log₂); shaded band is min/max range.
- Machine identity (CPU model, core count, Python version) is in each chart's subtitle so saved PNGs stay meaningful in isolation.

## Repository layout

```
lab/             # shared engine
  metrics.py     # Metrics dataclass + CSV round-trip
  workloads.py   # paradigm-agnostic CPU/I/O functions
  runner.py      # measure() with psutil sampler (aggregates parent + children)
  plot.py        # compare_bar, scaling_line
  mock_server.py # deterministic aiohttp test server
experiments/     # one file per experiment, top-to-bottom readable
pitfalls/        # teaching artefacts (broken/fixed demonstrations)
tests/           # pytest suite for the engine (NOT the experiments/pitfalls)
results/         # generated CSVs and PNGs (gitignored)
tmp_data/        # generated test files for experiment 03 (gitignored)
docs/
  superpowers/specs/   # design document
  superpowers/plans/   # implementation plan
  reference-results/   # snapshot run for comparison
_theory/               # concurrency theory notes (Polish + English)
```

## References

- `_theory/concurrency-pyth-en.md` — theoretical intro (start here if new).
- `docs/superpowers/specs/2026-04-17-concurrency-lab-design.md` — design document.
- `docs/superpowers/plans/2026-04-17-concurrency-lab.md` — implementation plan.
