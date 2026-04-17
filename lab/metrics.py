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
