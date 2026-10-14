"""Hand-rolled inline SVG: no runtime JS libraries, no CDNs. Every chart has a text alternative."""
from __future__ import annotations

import json
import math
from pathlib import Path

GRADE_COLOURS = {"Strong": "var(--accent)", "Moderate": "var(--snow-above)", "Weak": "var(--snow-near)", "No signal": "var(--snow-below)"}


def pct(p: float) -> int:
    """Round to the nearest 5 % (never show false precision)."""
    return int(5 * round(100 * p / 5))


def tercile_bar(t: dict, width: int = 320, height: int = 28, label_id: str = "") -> str:
    b, n, a = t["below"], t["near"], t["above"]
    x = 0
    parts = []
    for key, val, col in (("below", b, "var(--snow-below)"), ("near", n, "var(--snow-near)"), ("above", a, "var(--snow-above)")):
        w = width * val
        parts.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" fill="{col}" rx="0"/>')
        if val >= 0.12:
            parts.append(f'<text x="{x + w / 2:.1f}" y="{height * 0.68:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{"#fff" if key == "above" else "var(--ink-strong)"}">{pct(val)}%</text>')
        x += w
    return (f'<svg class="tercile" viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
            f'aria-labelledby="{label_id}" preserveAspectRatio="none">' + "".join(parts) + "</svg>")


def quintile_bar(q: list[float], width: int = 200, height: int = 44, highlight_top: bool = True) -> str:
    """Five bins; bar height = probability; the 20 % climatology line drawn across."""
    n = len(q)
    gap = 4
    bw = (width - gap * (n - 1)) / n
    parts = []
    maxp = max(0.4, max(q))
    for i, p in enumerate(q):
        h = (height - 12) * p / maxp
        col = f"var(--quint-{i + 1})"
        parts.append(f'<rect x="{i * (bw + gap):.1f}" y="{height - 12 - h:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{col}" rx="2"/>')
        parts.append(f'<text x="{i * (bw + gap) + bw / 2:.1f}" y="{height - 1}" text-anchor="middle" font-size="9" fill="var(--muted)">{pct(p)}</text>')
    yc = height - 12 - (height - 12) * 0.2 / maxp
    parts.append(f'<line x1="0" y1="{yc:.1f}" x2="{width}" y2="{yc:.1f}" stroke="var(--muted)" stroke-dasharray="3 3" stroke-width="1"/>')
    return f'<svg class="quint" viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-hidden="true">' + "".join(parts) + "</svg>"


def factor_bars(factors: list[dict], width: int = 300, row: int = 22) -> str:
    """Horizontal contribution bars centred at zero (logit contributions to P(above normal))."""
    if not factors:
        return ""
    m = max(0.3, max(abs(f["contribution"]) for f in factors))
    h = row * len(factors)
    cx = width * 0.55
    scale = (width * 0.42) / m
    parts = [f'<line x1="{cx:.1f}" y1="0" x2="{cx:.1f}" y2="{h}" stroke="var(--border)"/>']
    for i, f in enumerate(factors):
        y = i * row + 4
        c = f["contribution"]
        w = abs(c) * scale
        x = cx if c >= 0 else cx - w
        col = "var(--snow-above)" if c >= 0 else "var(--snow-below)"
        parts.append(f'<text x="0" y="{y + 11}" font-size="11" fill="var(--ink)">{f["name"]}</text>')
        parts.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w, 1):.1f}" height="{row - 8}" fill="{col}" rx="2"/>')
    return f'<svg class="factors" viewBox="0 0 {width} {h}" width="100%" height="{h}" role="img" aria-hidden="true">' + "".join(parts) + "</svg>"


def mjo_wheel(phase: int, amp: float, rmm1: float | None = None, rmm2: float | None = None, size: int = 120) -> str:
    c = size / 2
    r = size * 0.36
    parts = [f'<circle cx="{c}" cy="{c}" r="{r:.1f}" fill="none" stroke="var(--border)"/>',
             f'<circle cx="{c}" cy="{c}" r="{r / 3:.1f}" fill="var(--bg-alt)" stroke="var(--border)"/>']
    for k in range(8):
        a = math.radians(45 * k)
        parts.append(f'<line x1="{c + r / 3 * math.cos(a):.1f}" y1="{c - r / 3 * math.sin(a):.1f}" x2="{c + r * math.cos(a):.1f}" y2="{c - r * math.sin(a):.1f}" stroke="var(--border)"/>')
    # phase numbering: WH04 phases run anticlockwise from the lower-left (phase 1 at ~225 deg)
    for k in range(1, 9):
        a = math.radians(202.5 + 45 * (k - 1))
        parts.append(f'<text x="{c + r * 1.15 * math.cos(a):.1f}" y="{c - r * 1.15 * math.sin(a) + 3.5:.1f}" text-anchor="middle" font-size="9" fill="var(--muted)">{k}</text>')
    if rmm1 is None or rmm2 is None:
        a = math.radians(202.5 + 45 * (phase - 1))
        rmm1, rmm2 = amp * math.cos(a), amp * math.sin(a)
    px, py = c + min(amp, 3) / 3 * r * (rmm1 / max(amp, 1e-6)), c - min(amp, 3) / 3 * r * (rmm2 / max(amp, 1e-6))
    parts.append(f'<line x1="{c}" y1="{c}" x2="{px:.1f}" y2="{py:.1f}" stroke="var(--accent)" stroke-width="2"/>')
    parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="var(--accent)"/>')
    return f'<svg class="mjo" viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" aria-label="MJO phase {phase}, amplitude {amp:.1f}">' + "".join(parts) + "</svg>"


def season_chart(weeks: list[dict], width: int = 640, height: int = 200) -> str:
    """Observed weekly SNOW-W (mm w.e.) with climatology band; forecast tercile dots from leads 19/26."""
    if not weeks:
        return ""
    pad_l, pad_r, pad_t, pad_b = 36, 10, 10, 40
    n = len(weeks)
    ymax = max([w.get("clim_hi", 0) for w in weeks] + [w.get("obs") or 0 for w in weeks]) * 1.15 or 1
    def X(i): return pad_l + (width - pad_l - pad_r) * i / max(n - 1, 1)
    def Y(v): return pad_t + (height - pad_t - pad_b) * (1 - v / ymax)
    band = " ".join(f"{X(i):.1f},{Y(w['clim_hi']):.1f}" for i, w in enumerate(weeks)) + " " + " ".join(f"{X(i):.1f},{Y(w['clim_lo']):.1f}" for i, w in reversed(list(enumerate(weeks))))
    parts = [f'<polygon points="{band}" fill="var(--snow-near)" opacity=".35"/>']
    obs = [(X(i), Y(w["obs"])) for i, w in enumerate(weeks) if w.get("obs") is not None]
    if obs:
        parts.append('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in obs) + '" fill="none" stroke="var(--primary)" stroke-width="2.5"/>')
    for i, w in enumerate(weeks):
        for lead, mark in (("fc19", "▲"), ("fc26", "△")):
            f = w.get(lead)
            if f:
                col = "var(--snow-above)" if f == "above" else ("var(--snow-below)" if f == "below" else "var(--muted)")
                parts.append(f'<text x="{X(i) + (0 if lead == "fc19" else 7):.1f}" y="{height - pad_b + 13}" text-anchor="middle" font-size="9" fill="{col}">{mark}</text>')
        if i % max(1, n // 6) == 0:
            parts.append(f'<text x="{X(i):.1f}" y="{height - 6}" text-anchor="middle" font-size="10" fill="var(--muted)">{w["start"][5:]}</text>')
    for v in (0, ymax / 2, ymax):
        parts.append(f'<text x="{pad_l - 4}" y="{Y(v) + 4:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">{v:.0f}</text>')
        parts.append(f'<line x1="{pad_l}" y1="{Y(v):.1f}" x2="{width - pad_r}" y2="{Y(v):.1f}" stroke="var(--border)" stroke-width="1"/>')
    return f'<svg class="season" viewBox="0 0 {width} {height}" width="100%" role="img" aria-labelledby="season-desc">' + "".join(parts) + "</svg>"


def _lonlat_to_xy(lon: float, lat: float, box: dict, width: int, height: int):
    lon = lon % 360
    x = (lon - box["lon"][0]) / (box["lon"][1] - box["lon"][0]) * width
    y = (box["lat"][1] - lat) / (box["lat"][1] - box["lat"][0]) * height
    return x, y


MAP_QUINT = ["#e8e2d6", "#c9d6e3", "#93b4d2", "#4078c0", "#185078"]


def map_svg(grid: dict, coast: dict, boxes: dict[str, dict], domain: dict, title: str, width: int = 640,
            height: int | None = None, hokkaido: dict | None = None) -> str:
    """Most-likely-quintile shading with probability opacity, coastline, index boxes.

    grid: {"lats": [...], "lons": [...], "bin": [[...]], "prob": [[...]]} (bin 1..5, prob 0..1)
    coast: GeoJSON FeatureCollection of LineStrings/MultiLineStrings (Natural Earth 110m).
    """
    lat0, lat1 = domain["lat"]; lon0, lon1 = domain["lon"]
    if height is None:
        height = int(width * (lat1 - lat0) / (lon1 - lon0) * 1.35)  # mild N-S stretch for a plate carree look
    lats, lons = grid["lats"], grid["lons"]
    dlat = abs(lats[1] - lats[0]); dlon = abs(lons[1] - lons[0])
    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f6f8fa"/>']
    for i, la in enumerate(lats):
        j = 0
        while j < len(lons):  # run-length merge of identical cells along a row
            b = grid["bin"][i][j]; p = grid["prob"][i][j]
            if b is None:
                j += 1; continue
            op = round(0.15 + 0.85 * max(0.0, min(1.0, (p - 0.2) / 0.5)), 1)
            k = j
            while k + 1 < len(lons) and grid["bin"][i][k + 1] == b and grid["prob"][i][k + 1] is not None and round(0.15 + 0.85 * max(0.0, min(1.0, (grid["prob"][i][k + 1] - 0.2) / 0.5)), 1) == op:
                k += 1
            x, y = _lonlat_to_xy(lons[j] - dlon / 2, la + dlat / 2, domain, width, height)
            x2, y2 = _lonlat_to_xy(lons[k] + dlon / 2, la - dlat / 2, domain, width, height)
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{x2 - x + 0.3:.1f}" height="{y2 - y + 0.3:.1f}" fill="{MAP_QUINT[b - 1]}" opacity="{op}"/>')
            j = k + 1
    for feat in coast["features"]:
        geom = feat["geometry"]
        lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for line in lines:
            pts = []
            prev = None
            for lon, lat in line:
                lon360 = lon % 360
                inside = lat0 - 2 <= lat <= lat1 + 2 and lon0 - 2 <= lon360 <= lon1 + 2
                if inside:
                    x, y = _lonlat_to_xy(lon360, lat, domain, width, height)
                    if prev is not None and abs(lon360 - prev) > 180:
                        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#3a3a3a" stroke-width="1" opacity=".8"/>'); pts = []
                    pts.append(f"{x:.1f},{y:.1f}"); prev = lon360
                else:
                    if len(pts) > 1:
                        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#3a3a3a" stroke-width="1" opacity=".8"/>')
                    pts = []; prev = None
            if len(pts) > 1:
                parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#3a3a3a" stroke-width="1" opacity=".8"/>')
    for key, bx in boxes.items():
        x, y = _lonlat_to_xy(bx["lon"][0], bx["lat"][1], domain, width, height)
        x2, y2 = _lonlat_to_xy(bx["lon"][1], bx["lat"][0], domain, width, height)
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{x2 - x:.1f}" height="{y2 - y:.1f}" fill="none" stroke="#e01c1e" stroke-width="1.5" stroke-dasharray="4 3"/>')
        parts.append(f'<text x="{x + 4:.1f}" y="{y + 12:.1f}" font-family="Lato,Arial,sans-serif" font-size="11" font-weight="700" fill="#e01c1e">{key}</text>')
    if hokkaido:
        x, y = _lonlat_to_xy(hokkaido["lon"][0], hokkaido["lat"][1], domain, width, height)
        x2, y2 = _lonlat_to_xy(hokkaido["lon"][1], hokkaido["lat"][0], domain, width, height)
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{x2 - x:.1f}" height="{y2 - y:.1f}" fill="none" stroke="#0a0101" stroke-width="2"/>')
    legend = "".join(f'<rect x="{width - 130 + i * 24}" y="{height - 22}" width="22" height="12" fill="{MAP_QUINT[i]}"/>' for i in range(5))
    legend += f'<text x="{width - 130}" y="{height - 26}" font-family="Lato,Arial,sans-serif" font-size="10" fill="#3a3a3a">most likely quintile (low → high)</text>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{title}">' +
            "".join(parts) + legend + "</svg>")


def load_coast(path: Path) -> dict:
    return json.loads(Path(path).read_text())
