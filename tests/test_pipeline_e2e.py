"""End to end on synthetic data: members -> thresholds -> PBC -> forecast JSON -> validation -> site.
Then the built site is checked: schema-valid latest.json, no runtime requests to third parties, text
alternatives for every chart, page weight, and the Normie/Nerd toggle behaviour in a real browser."""
import datetime as dt
import glob
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from conftest import GT_DELTA, K, LEAD
from dokayuki.config import load_indices
from dokayuki.forecast import assemble_forecast
from dokayuki.pbc import run_pbc
from dokayuki.site.build import build
from dokayuki.site.references import render as render_refs
from dokayuki.validate import check_forecast_json

ROOT = Path(__file__).resolve().parents[1]
CHROME = next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))), None)


@pytest.fixture(scope="module")
def built(synth, tmp_path_factory):
    F, O, targets = synth["F"], synth["O"], synth["targets"]
    res = run_pbc(F, F, O, targets, GT_DELTA, LEAD, K, scope="per_target")
    # relabel the synthetic targets as real index keys and pretend lead 26 equals lead 19
    keys = ["MOI", "SJI", "SHI"]
    P = res.pbc.assign_coords(target=keys)
    t_star = pd.Timestamp(targets[-1])
    init = (t_star - pd.Timedelta(days=LEAD - 1)).date()
    P26 = P.assign_coords(time=P.time + pd.Timedelta(days=7))
    skill = {k: {19: {"rpss": 0.06, "ci": [0.01, 0.11], "lift": {"lift": 0.02, "ci": [0.0, 0.04], "significant": True}},
                 26: {"rpss": 0.02, "ci": [-0.02, 0.06], "lift": {"lift": 0.0, "ci": [-0.03, 0.03], "significant": False}}} for k in keys}
    drivers = {"ao": {"value": -0.8, "date": "x"}, "mjo": {"phase": 5, "amp": 1.1, "rmm1": None, "rmm2": None, "date": "x"},
               "vortex": {"u10": 15.0, "state": "normal", "date": "x"}, "sst_anom": 0.4, "recent_snow": {}}
    d = assemble_forecast(issued=init + dt.timedelta(days=2), init=init, index_cdfs={19: P, 26: P26}, index_defs=load_indices(),
                          index_skill=skill, snow=None, drivers=drivers, generated_at="2026-01-01T00:00:00Z")
    d["references"] = render_refs()
    rep = check_forecast_json(d)
    assert rep.ok, rep.problems
    out = tmp_path_factory.mktemp("site")
    build(d, out)
    return d, out


def test_forecast_json_round_trips_and_is_causal(built):
    d, out = built
    j = json.loads((out / "latest.json").read_text())
    assert check_forecast_json(j).ok
    assert not d["snow_model"]["skilful"] and all(w["grade"] == "No signal" for w in d["weeks"])
    for ix in d["indices"]:
        assert abs(sum(ix["quintiles"]["19"]) - 1) < 1e-6
    assert dt.date.fromisoformat(d["weeks"][0]["valid"][0]) > dt.date.fromisoformat(d["issued"])


def test_site_has_no_third_party_runtime_requests(built):
    _, out = built
    html = (out / "index.html").read_text() + (out / "method.html").read_text() + (out / "embed.html").read_text()
    for m in re.finditer(r'<(?:script|link|img)[^>]+(?:src|href)="([^"]+)"', html):
        url = m.group(1)
        assert not url.startswith(("http://", "https://", "//")), f"runtime request to {url}"
    assert "fonts.googleapis.com" not in html and "cdn." not in html
    assert "cookie" not in html.lower()


def test_site_accessibility_basics(built):
    _, out = built
    html = (out / "index.html").read_text()
    for m in re.finditer(r"<img[^>]*>", html):
        assert 'alt="' in m.group(0), m.group(0)
    for m in re.finditer(r'<svg[^>]*role="img"[^>]*>', html):
        assert "aria-label" in m.group(0) or "aria-labelledby" in m.group(0), m.group(0)
    assert "<main" in html and 'class="skip"' in html and "<h1" in html
    assert "This is not an avalanche or mountain weather forecast" in html


def test_page_weight_budget(built):
    _, out = built
    html = (out / "index.html").stat().st_size
    css = sum(f.stat().st_size for f in (out / "static").glob("*.css")) + (out / "design-tokens.css").stat().st_size
    js = sum(f.stat().st_size for f in (out / "static").glob("*.js"))
    fonts = sum(f.stat().st_size for f in (out / "assets" / "fonts").glob("*.woff2"))
    assert html + css + js + fonts < 500_000, (html, css, js, fonts)


def test_unverified_references_never_render(tmp_path):
    bib = tmp_path / "r.bib"; chk = tmp_path / "c.md"
    bib.write_text("@article{ok1, title={Good}, author={A, B}, journal={J}, year={2020}, doi={10.1/x}}\n@article{bad1, title={Bad}, author={C, D}, journal={J}, year={2021}}\n")
    chk.write_text("| key | citation | DOI | claim | status | checked | notes |\n|---|---|---|---|---|---|---|\n| ok1 | x | 10.1/x | c | yes | a | |\n| bad1 | y | none | c | UNVERIFIED | - | |\n")
    keys = {r["key"] for r in render_refs(bib, chk)}
    assert keys == {"ok1"}


@pytest.mark.skipif(CHROME is None, reason="no bundled chromium")
def test_mode_toggle_in_browser(built):
    from playwright.sync_api import sync_playwright
    _, out = built
    url = (out / "index.html").as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        pg = b.new_page(viewport={"width": 375, "height": 800})
        pg.goto(url); pg.wait_for_timeout(100)
        assert pg.evaluate("document.documentElement.getAttribute('data-mode')") == "normie"
        assert pg.evaluate("getComputedStyle(document.querySelector('.indices')).display") == "none"
        pg.click('[data-set-mode="nerd"]'); pg.wait_for_timeout(50)
        assert pg.evaluate("document.documentElement.getAttribute('data-mode')") == "nerd"
        assert pg.evaluate("getComputedStyle(document.querySelector('.indices')).display") != "none"
        assert pg.evaluate("localStorage.getItem('hpo-mode')") == "nerd"
        pg.goto(url); pg.wait_for_timeout(100)                     # persists
        assert pg.evaluate("document.documentElement.getAttribute('data-mode')") == "nerd"
        pg.goto(url + "?mode=normie"); pg.wait_for_timeout(100)    # URL wins for sharing
        assert pg.evaluate("document.documentElement.getAttribute('data-mode')") == "normie"
        assert pg.evaluate("document.documentElement.scrollWidth") <= 375
        b.close()
