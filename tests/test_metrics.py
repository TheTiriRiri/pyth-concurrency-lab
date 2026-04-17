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


def test_append_csv_creates_file_with_header(tmp_csv: Path):
    m = Metrics("e", "threading", 4, 4, 1.0, 300.0, 50.0, {"payload": 1024})
    append_csv(tmp_csv, m)

    assert tmp_csv.exists()
    # Header is always a plain first line; CSV escaping does not affect it
    # because none of the column names contain special characters.
    first_line = tmp_csv.read_text().splitlines()[0]
    assert first_line == "experiment,paradigm,workers,n_tasks,duration_s,cpu_percent_avg,mem_mb_peak,extra_json"

    # The extra dict must survive round-trip — this is what actually matters.
    rows = load_csv(tmp_csv)
    assert len(rows) == 1
    assert rows[0].extra == {"payload": 1024}


def test_append_csv_handles_comma_in_extra(tmp_csv: Path):
    """extra values with commas must round-trip through csv.writer quoting."""
    m = Metrics("e", "threading", 4, 4, 1.0, 300.0, 50.0, {"note": "a,b,c"})
    append_csv(tmp_csv, m)
    rows = load_csv(tmp_csv)
    assert rows[0].extra == {"note": "a,b,c"}


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
