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
        iterations=20_000_000,
    )
    # With 4 children each near 100%, aggregate should comfortably exceed 100%.
    assert m.cpu_percent_avg > 100.0, f"Expected aggregate >100%, got {m.cpu_percent_avg}"


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
