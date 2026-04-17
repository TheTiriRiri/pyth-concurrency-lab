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

    # Known paradigms first, then any custom labels (e.g. experiment 05 variants).
    ordered = [p for p in _PARADIGM_ORDER if p in grouped]
    extras = [p for p in grouped if p not in _PARADIGM_ORDER]
    paradigms = ordered + extras

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
