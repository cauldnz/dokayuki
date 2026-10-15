"""One-screen status of the S2S history pull, for a person or an agent looking at the container.

    docker exec dokayuki-s2s .venv/bin/python scripts/pull_status.py          # text
    docker exec dokayuki-s2s .venv/bin/python scripts/pull_status.py --json   # machine-readable

Also written to logs/status.json after every loop of pull_history_s2s.sh.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]


def members_summary() -> dict:
    import xarray as xr
    out = {}
    for p in sorted((ROOT / "state" / "members").glob("*/*/*.nc")):
        da = xr.open_dataarray(p)
        issues = sorted(str(x)[:10] for x in da["issue"].values)
        out[str(p.relative_to(ROOT))] = {"issues": len(issues), "first": issues[0], "last": issues[-1],
                                         "members": int(da.sizes.get("member", 0)), "hyears": int(da.sizes.get("hyear", 0)),
                                         "targets": list(map(str, da["target"].values)), "kb": round(p.stat().st_size / 1024)}
    return out


def log_summary() -> dict:
    log = ROOT / "logs" / "pull_history_s2s.log"
    if not log.exists():
        return {}
    lines = log.read_text(errors="replace").splitlines()
    decoded = [l for l in lines if "MB, decoded" in l]
    failed = [l for l in lines if "failed:" in l or "decode failed" in l or "incomplete" in l]
    last = lines[-1][:200] if lines else ""
    mb = sum(float(m.group(1)) for l in decoded for m in [re.search(r": (\d+) MB", l)] if m)
    return {"months_decoded": len(decoded), "grib_mb_total": round(mb), "problems": len(failed),
            "last_problem": failed[-1][:200] if failed else "", "last_line": last,
            "last_decoded": decoded[-1][:160] if decoded else ""}


def main():
    a = argparse.ArgumentParser(); a.add_argument("--json", action="store_true"); a = a.parse_args()
    reqs = ROOT / "state" / "requests.json"
    status = {
        "asof": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "requests_in_flight": len(json.loads(reqs.read_text())) if reqs.exists() else 0,
        "grib_on_disk_mb": round(sum(p.stat().st_size for p in (ROOT / "state" / "grib").rglob("*.grib")) / 1e6) if (ROOT / "state" / "grib").exists() else 0,
        "log": log_summary(),
        "members": members_summary(),
    }
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "status.json").write_text(json.dumps(status, indent=1))
    if a.json:
        print(json.dumps(status, indent=1)); return
    print(f"as of {status['asof']}: {status['log'].get('months_decoded', 0)} months decoded, "
          f"{status['log'].get('grib_mb_total', 0)} MB pulled, {status['requests_in_flight']} request ids held, "
          f"{status['grib_on_disk_mb']} MB GRIB on disk, {status['log'].get('problems', 0)} problems")
    for k, v in status["members"].items():
        print(f"  {k}: {v['issues']} issues {v['first']}..{v['last']}, {v['members']} members"
              + (f" x {v['hyears']} hyears" if v['hyears'] else "") + f", {len(v['targets'])} targets, {v['kb']} KB")
    if status["log"].get("last_problem"):
        print("  last problem:", status["log"]["last_problem"])
    print("  last log line:", status["log"].get("last_line", ""))


if __name__ == "__main__":
    main()
