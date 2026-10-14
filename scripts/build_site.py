"""Build the static site. --fixture strong|none|stale renders a design fixture; otherwise uses --forecast JSON."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dokayuki.site.build import build
from dokayuki.site.fixtures import make_state
from dokayuki.validate import check_forecast_json
p = argparse.ArgumentParser(); p.add_argument("--fixture"); p.add_argument("--forecast"); p.add_argument("--out", default="site/build")
a = p.parse_args()
d = make_state(a.fixture) if a.fixture else json.loads(Path(a.forecast).read_text())
check_forecast_json(d).raise_if_failed()   # never build a page from an invalid forecast
out = build(d, Path(a.out))
size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file() and "assets/geo" not in str(f) and "archive" not in str(f))
print(f"built {out} ({len(list(out.rglob('*')))} files); page weight excl. geo/archive: {size/1024:.0f} KB; index.html {(out/'index.html').stat().st_size/1024:.0f} KB")
