"""Publish and fetch state/ as versioned GitHub Release assets (chunks <= 1.9 GB).

Raw GRIB (state/grib/) is excluded: it is kept locally for reprocessing but is too large,
and not derived state, to publish.

Usage: state_release.py download | upload [--keep N]
Needs GITHUB_TOKEN and GITHUB_REPOSITORY (set in Actions); locally pass --repo owner/name.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import tarfile
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
CHUNK = 1_900_000_000
API = "https://api.github.com"


def _hdr():
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}


def _repo(a):
    return a.repo or os.environ.get("GITHUB_REPOSITORY")


def pack() -> list[Path]:
    out = ROOT / "state_pack"; out.mkdir(exist_ok=True)
    tar = out / "state.tar"
    with tarfile.open(tar, "w") as t:
        for p in sorted(STATE.rglob("*")):
            if (p.is_file() and p.name != "README.md" and "requests.json" not in p.name
                    and "grib" not in p.relative_to(STATE).parts):
                t.add(p, arcname=str(p.relative_to(STATE)))
    parts = []
    with open(tar, "rb") as fh:
        i = 0
        while True:
            buf = fh.read(CHUNK)
            if not buf:
                break
            part = out / f"state.tar.{i:03d}"; part.write_bytes(buf); parts.append(part); i += 1
    tar.unlink()
    manifest = {"created": dt.datetime.now(dt.timezone.utc).isoformat(), "parts": [p.name for p in parts],
                "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in parts}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return parts + [out / "manifest.json"]


def upload(a):
    repo = _repo(a)
    tag = "state-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    r = requests.post(f"{API}/repos/{repo}/releases", headers=_hdr(), json={"tag_name": tag, "name": tag, "prerelease": True,
                      "body": "dokayuki state snapshot (weekly truth, member index values, observed predictors)."}, timeout=60)
    r.raise_for_status(); rel = r.json()
    for f in pack():
        with open(f, "rb") as fh:
            up = requests.post(rel["upload_url"].split("{")[0], params={"name": f.name}, headers={**_hdr(), "Content-Type": "application/octet-stream"}, data=fh, timeout=3600)
            up.raise_for_status()
    rels = requests.get(f"{API}/repos/{repo}/releases", headers=_hdr(), params={"per_page": 100}, timeout=60).json()
    state_rels = sorted([x for x in rels if x["tag_name"].startswith("state-")], key=lambda x: x["tag_name"], reverse=True)
    for old in state_rels[a.keep:]:
        requests.delete(f"{API}/repos/{repo}/releases/{old['id']}", headers=_hdr(), timeout=60)
        requests.delete(f"{API}/repos/{repo}/git/refs/tags/{old['tag_name']}", headers=_hdr(), timeout=60)
    print("uploaded", tag)


def download(a):
    repo = _repo(a)
    rels = requests.get(f"{API}/repos/{repo}/releases", headers=_hdr(), params={"per_page": 100}, timeout=60).json()
    state_rels = sorted([x for x in rels if x["tag_name"].startswith("state-")], key=lambda x: x["tag_name"], reverse=True)
    if not state_rels:
        print("no state release yet; starting from an empty state/"); STATE.mkdir(exist_ok=True); return
    rel = state_rels[0]; out = ROOT / "state_pack"; out.mkdir(exist_ok=True)
    assets = {x["name"]: x for x in rel["assets"]}
    manifest = json.loads(requests.get(assets["manifest.json"]["url"], headers={**_hdr(), "Accept": "application/octet-stream"}, timeout=60).content)
    with open(out / "state.tar", "wb") as tar:
        for name in manifest["parts"]:
            data = requests.get(assets[name]["url"], headers={**_hdr(), "Accept": "application/octet-stream"}, timeout=3600).content
            assert hashlib.sha256(data).hexdigest() == manifest["sha256"][name], f"checksum mismatch {name}"
            tar.write(data)
    STATE.mkdir(exist_ok=True)
    with tarfile.open(out / "state.tar") as t:
        t.extractall(STATE, filter="data")
    print("downloaded", rel["tag_name"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("cmd", choices=["download", "upload"]); p.add_argument("--keep", type=int, default=5); p.add_argument("--repo")
    a = p.parse_args(); (download if a.cmd == "download" else upload)(a)
