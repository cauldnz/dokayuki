"""Render the static site from a forecast JSON (latest.json) and the site config."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from ..config import ROOT, load_indices, load_yaml
from . import charts

SITE_DIR = ROOT / "site"
INDEX_HELP = {
    "SHI": "Mean sea-level pressure over Mongolia and southern Siberia (40–65°N, 80–120°E). A strong Siberian High is the cold reservoir behind every outbreak. Higher = stronger high.",
    "ALI": "Mean sea-level pressure over the North Pacific (30–65°N, 160°E–140°W), sign flipped so higher = deeper Aleutian Low. Together with the Siberian High it sets the pressure gradient across Japan.",
    "MOI": "Pressure at Irkutsk minus pressure at Nemuro (the JMA winter monsoon index). Higher = stronger northwesterly monsoon flow over the Sea of Japan.",
    "SJC": "850 hPa temperature over the Sea of Japan (38–46°N, 132–141°E), sign flipped so higher = colder air aloft.",
    "SJI": "Sea-surface minus 850 hPa temperature over the same box. Above about 13 °C the air over the sea goes convective and snow bands form; higher = more convective.",
    "EAT": "500 hPa height over Japan and the Yellow Sea (30–45°N, 125–145°E), sign flipped so higher = deeper East Asian trough, which steers outbreaks into Hokkaido.",
}


def index_glyph(key: str) -> Markup:
    """Tiny diagrams of what each index means (inline SVG, decorative)."""
    g = {
        "SHI": '<circle cx="20" cy="20" r="12" fill="none" stroke="#fff" stroke-width="2"/><text x="20" y="25" text-anchor="middle" font-size="13" font-weight="900" fill="#fff">H</text>',
        "ALI": '<circle cx="20" cy="20" r="12" fill="none" stroke="#fff" stroke-width="2"/><text x="20" y="25" text-anchor="middle" font-size="13" font-weight="900" fill="#fff">L</text>',
        "MOI": '<text x="7" y="16" font-size="11" font-weight="900" fill="#fff">H</text><text x="26" y="32" font-size="11" font-weight="900" fill="#fff">L</text><path d="M12 20 L28 22" stroke="#fff" stroke-width="2" marker-end="url(#a)"/><path d="M24 18 l5 4 -5 4" fill="none" stroke="#fff" stroke-width="2"/>',
        "SJC": '<path d="M8 30 Q20 10 32 30" fill="none" stroke="#fff" stroke-width="2"/><text x="20" y="14" text-anchor="middle" font-size="10" font-weight="900" fill="#fff">cold</text>',
        "SJI": '<path d="M6 30 q4-4 8 0 t8 0 t8 0 t8 0" fill="none" stroke="#fff" stroke-width="2"/><path d="M14 22 v-6 M20 22 v-9 M26 22 v-6" stroke="#fff" stroke-width="2"/>',
        "EAT": '<path d="M6 12 Q20 36 34 12" fill="none" stroke="#fff" stroke-width="2.5"/>',
    }[key]
    return Markup(f'<svg viewBox="0 0 40 40" aria-hidden="true">{g}</svg>')


def pipeline_svg() -> Markup:
    steps = ["ECMWF + JMA\nensembles", "per-member\nindices", "PBC\ncalibration", "index odds +\nobserved state", "snow-week\nodds"]
    w, bw, gap = 760, 128, 28
    parts = []
    for i, s in enumerate(steps):
        x = i * (bw + gap)
        parts.append(f'<rect x="{x}" y="10" width="{bw}" height="56" rx="6" fill="var(--bg-alt)" stroke="var(--primary)" stroke-width="1.5"/>')
        for j, line in enumerate(s.split("\n")):
            parts.append(f'<text x="{x + bw / 2}" y="{34 + j * 16}" text-anchor="middle" font-size="12" font-weight="700" fill="var(--ink-strong)">{line}</text>')
        if i < len(steps) - 1:
            parts.append(f'<path d="M{x + bw + 4} 38 h{gap - 10} m-6 -5 l6 5 -6 5" fill="none" stroke="var(--muted)" stroke-width="2"/>')
    return Markup(f'<svg viewBox="0 0 {w} 76" width="100%" role="img" aria-label="Pipeline diagram">{"".join(parts)}</svg>')


def _write_map(m: dict, out: Path, coast, boxes, region, hok) -> str:
    svg = charts.map_svg(m["grid"], coast, boxes, {"lat": region["domain"]["lat"], "lon": region["domain"]["lon"]},
                         m["title"], hokkaido={"lat": hok["lat"], "lon": hok["lon"]})
    (out / "maps").mkdir(parents=True, exist_ok=True)
    name = f"maps/{m['field']}-{m['lead']}.svg"
    (out / name).write_text(svg)
    return name


def make_env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(SITE_DIR / "templates")), autoescape=select_autoescape(["html", "j2"]))
    coast = charts.load_coast(SITE_DIR / "assets" / "geo" / "ne_110m_coastline.geojson")
    region = load_yaml("region")
    idx = load_indices()
    boxes = {k: {"lat": list(v.box.lat), "lon": list(v.box.lon)} for k, v in idx.items() if v.box is not None and k in ("SHI", "ALI", "SJC", "EAT")}
    hok = region["masks"]["hokkaido_land"]
    env.globals.update(
        pct=charts.pct,
        tercile_bar=lambda t, width=320, height=28, label_id="": Markup(charts.tercile_bar(t, width, height, label_id)),
        quintile_bar=lambda q: Markup(charts.quintile_bar(q)),
        factor_bars=lambda f: Markup(charts.factor_bars(f)),
        mjo_wheel=lambda ph, amp, r1=None, r2=None, size=120: Markup(charts.mjo_wheel(ph, amp, r1, r2, size)),
        season_chart=lambda s: Markup(charts.season_chart(s)),
        map_file=lambda m, out: _write_map(m, out, coast, boxes, region, hok),
        index_glyph=index_glyph, index_help=lambda k: INDEX_HELP.get(k, ""), pipeline_svg=pipeline_svg,
    )
    return env


def build(forecast: dict, out: Path, site_cfg: dict | None = None, archive: list[dict] | None = None) -> Path:
    site = site_cfg or load_yaml("site")
    env = make_env()
    out.mkdir(parents=True, exist_ok=True)
    for m in forecast.get("maps", []):
        m["file"] = env.globals["map_file"](m, out)
    (out / "index.html").write_text(env.get_template("index.html.j2").render(
        site=site, d=forecast, rel="", page_title="Weeks 3 & 4", meta_description=forecast["headline"]))
    (out / "method.html").write_text(env.get_template("method.html.j2").render(
        site=site, d=forecast, rel="", page_title="Method and trust", meta_description="How the outlook is made and how much to trust it."))
    (out / "embed.html").write_text(env.get_template("embed.html.j2").render(site=site, d=forecast))
    slim = {k: v for k, v in forecast.items() if k != "maps"}   # maps are files, not JSON payload
    slim["maps"] = [{k: v for k, v in m.items() if k != "grid"} for m in forecast.get("maps", [])]
    (out / "latest.json").write_text(json.dumps(slim, indent=1, default=str))
    arch = out / "archive"; arch.mkdir(exist_ok=True)
    (arch / f"{forecast['issued']}.json").write_text(json.dumps(slim, indent=1, default=str))
    items = sorted(p.name for p in arch.glob("*.json"))
    (arch / "index.html").write_text("<!doctype html><meta charset=utf-8><title>Archive</title><h1>Outlook archive</h1><ul>" +
                                     "".join(f'<li><a href="{n}">{n[:-5]}</a></li>' for n in reversed(items)) + "</ul>")
    (arch / "index.json").write_text(json.dumps(items))
    for sub in ("assets", "static"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
        shutil.copytree(SITE_DIR / sub, out / sub, ignore=shutil.ignore_patterns("*.md", "geo"))
    shutil.copy(SITE_DIR / "design-tokens.css", out / "design-tokens.css")
    (out / ".nojekyll").write_text("")
    return out
