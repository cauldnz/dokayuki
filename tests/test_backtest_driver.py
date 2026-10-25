"""The Phase 3 driver runs end to end on synthetic sources, never touches sealed winters, and its
outputs are valid (BACKTEST.md written and labelled, latest.json schema-valid)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dokayuki.validate import check_forecast_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.timeout(1500)
def test_synthetic_backtest_driver(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_backtest.py"), "--synthetic", "--output-root", str(tmp_path)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-2000:]
    md = (tmp_path / "docs" / "BACKTEST.md").read_text()
    assert "SYNTHETIC DATA" in md and "2023/24" in md and "lift" in md.lower()
    d = json.loads((tmp_path / "state" / "latest.json").read_text())
    assert check_forecast_json(d).ok and d["preview"] is True
    assert {ix["key"] for ix in d["indices"]} == {"MOI", "SJI", "SHI", "EAT"}
    # sealed winters never appear among scored seasons
    for line in md.splitlines():
        if line.startswith("| duet") or line.startswith("| ecmwf") or line.startswith("| jma"):
            assert "2024/25" not in line and "2025/26" not in line
