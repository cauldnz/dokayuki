"""Append-only experiment log (spec update 1 §6). Every configuration evaluated is recorded, and the
number of trials is reported beside the best result. Never evaluate on the locked final-exam winters."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .config import ROOT, SnowConfig

LOG = ROOT / "experiments" / "log.csv"
FIELDS = ["date", "experiment_id", "phase", "hypothesis", "settings", "cv_score", "cv_metric", "n_trials_so_far",
          "looked_at_final_exam", "notes"]


def locked_winters() -> tuple[str, ...]:
    return tuple(SnowConfig.load().raw["season"]["locked_final_exam_winters"])


def n_trials(log: Path = LOG) -> int:
    if not log.exists():
        return 0
    with open(log, newline="", encoding="utf-8") as fh:
        return max(0, sum(1 for _ in fh) - 1)


def record(experiment_id: str, phase: str, hypothesis: str, settings: dict, cv_score: float, cv_metric: str,
           notes: str = "", looked_at_final_exam: bool = False, log: Path = LOG) -> int:
    """Append one trial; returns the running trial count."""
    log.parent.mkdir(parents=True, exist_ok=True)
    new = not log.exists()
    n = n_trials(log) + 1
    with open(log, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"date": dt.date.today().isoformat(), "experiment_id": experiment_id, "phase": phase,
                    "hypothesis": hypothesis, "settings": repr(settings), "cv_score": f"{cv_score:.4f}",
                    "cv_metric": cv_metric, "n_trials_so_far": n, "looked_at_final_exam": looked_at_final_exam,
                    "notes": notes})
    return n


def assert_not_locked(seasons) -> None:
    bad = set(seasons) & set(locked_winters())
    if bad:
        raise RuntimeError(f"locked final-exam winters touched: {sorted(bad)}")
