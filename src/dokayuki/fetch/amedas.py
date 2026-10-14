"""AMeDAS daily snowfall / snow depth from the JMA data-download portal (manual pull, see docs/AMEDAS.md).

The portal (https://www.data.jma.go.jp/risk/obsdl/) writes Shift-JIS CSV with a multi-row header:
    row 1: "ダウンロードした時刻：..."
    row 2: blank
    row 3: station names (repeated per column)
    row 4: element names (降雪量合計(cm), 最深積雪(cm), ...)
    row 5: sub-headers (blank / 品質情報 / 均質番号)
    then: 年月日, values...
This parser is tolerant: it finds the header rows by content, keeps only value columns, and
returns a tidy DataFrame (time, station, element, value). Licence: JMA Public Data License;
credit 出典：気象庁ホームページ.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

ELEMENTS = {"降雪量合計(cm)": "snowfall_cm", "最深積雪(cm)": "snow_depth_max_cm", "降水量の合計(mm)": "precip_mm",
            "平均気温(℃)": "tmean_c", "日照時間(時間)": "sunshine_h"}


def parse_obsdl_csv(path: Path | str, encoding: str = "cp932") -> pd.DataFrame:
    raw = Path(path).read_bytes().decode(encoding, errors="replace")
    lines = raw.splitlines()
    # find the station-name row: the first row after the download stamp whose cells repeat a station name
    start = next(i for i, l in enumerate(lines) if l.startswith("年月日") or l.startswith('"年月日"'))
    station_row, element_row = None, None
    for i in range(start - 1, max(start - 5, -1), -1):
        cells = [c.strip('"') for c in lines[i].split(",")]
        if any(e in cells for e in ELEMENTS) and element_row is None:
            element_row = cells
        elif element_row is not None and any(cells[1:]):
            station_row = cells; break
    if station_row is None or element_row is None:
        raise ValueError(f"could not find the header rows in {path}")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), header=None)
    time = pd.to_datetime(df.iloc[1:, 0].astype(str).str.replace("/", "-"), errors="coerce")
    rows = []
    sub = [c.strip('"') for c in lines[start].split(",")]
    for j in range(1, df.shape[1]):
        if j >= len(element_row) or j >= len(station_row):
            continue
        if sub[j] not in ("", "値") and sub[j] in ("品質情報", "均質番号"):
            continue
        el = ELEMENTS.get(element_row[j])
        if el is None:
            continue
        vals = pd.to_numeric(df.iloc[1:, j], errors="coerce")
        rows.append(pd.DataFrame({"time": time.values, "station": station_row[j], "element": el, "value": vals.values}))
    out = pd.concat(rows, ignore_index=True).dropna(subset=["time"])
    return out


def load_amedas_dir(folder: Path) -> pd.DataFrame:
    frames = [parse_obsdl_csv(p) for p in sorted(Path(folder).glob("*.csv"))]
    if not frames:
        return pd.DataFrame(columns=["time", "station", "element", "value"])
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["time", "station", "element"], keep="last")
    return df.sort_values(["station", "element", "time"]).reset_index(drop=True)


def weekly_station_snowfall(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly (7-day, labelled by start) snowfall sum per station for comparison with SNOW-W."""
    s = df[df.element == "snowfall_cm"].pivot(index="time", columns="station", values="value").asfreq("D")
    return s.rolling(7).sum().shift(-6).dropna(how="all")
