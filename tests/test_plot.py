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


def test_compare_bar_includes_unknown_paradigm(tmp_path: Path):
    """Experiment 05 uses non-standard paradigm labels (e.g. 'asyncio + executor');
    compare_bar must render them, not silently drop them."""
    csv = tmp_path / "m.csv"
    append_csv(csv, Metrics("e", "threading", 4, 4, 1.0, 100.0, 30.0, {}))
    append_csv(csv, Metrics("e", "asyncio + executor", 4, 4, 0.5, 250.0, 40.0, {}))
    out = tmp_path / "m.png"
    compare_bar(csv, out)
    assert out.exists() and out.stat().st_size > 0
