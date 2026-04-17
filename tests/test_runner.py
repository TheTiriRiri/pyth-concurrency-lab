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
