"""Typed access to the YAML configuration files."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or CONFIG_DIR) / f"{name}.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class TimeConfig:
    leads: tuple[int, ...] = (19, 26)
    aggregation_days: int = 7
    measurement_lag_days: int = 10
    climatology_years: int = 20
    threshold_day_offsets: tuple[int, ...] = (-4, -2, 0, 2, 4)

    def forecast_delta(self, lead: int) -> int:
        """Days from init to the start of the target week (lead 19 -> 18)."""
        return int(lead) - 1

    def gt_delta(self, lead: int) -> int:
        """Days from target start back to the last fully observable truth week start."""
        return self.forecast_delta(lead) + self.measurement_lag_days


@dataclass(frozen=True)
class Box:
    lat: tuple[float, float]
    lon: tuple[float, float]
    land_only: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Box":
        return cls(lat=tuple(d["lat"]), lon=tuple(d["lon"]), land_only=bool(d.get("land_only", False)))


@dataclass(frozen=True)
class RegionConfig:
    resolution_deg: float
    lat_origin: float
    lon_origin: float
    domain: Box
    masks: dict[str, Box]
    time: TimeConfig
    variables: dict[str, dict[str, Any]]
    K_quintile: int = 5
    K_extreme: int = 20

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "RegionConfig":
        raw = load_yaml("region", config_dir)
        t = raw["time"]
        return cls(
            resolution_deg=float(raw["grid"]["resolution_deg"]),
            lat_origin=float(raw["grid"]["lat_origin"]),
            lon_origin=float(raw["grid"]["lon_origin"]),
            domain=Box.from_dict(raw["domain"]),
            masks={k: Box.from_dict(v) for k, v in raw["masks"].items()},
            time=TimeConfig(
                leads=tuple(int(x) for x in t["leads"]),
                aggregation_days=int(t["aggregation_days"]),
                measurement_lag_days=int(t["measurement_lag_days"]),
                climatology_years=int(t["climatology_years"]),
                threshold_day_offsets=tuple(int(x) for x in t["threshold_day_offsets"]),
            ),
            variables=raw["variables"]["model"],
            K_quintile=int(raw["quantiles"]["K_quintile"]),
            K_extreme=int(raw["quantiles"]["K_extreme"]),
        )


@dataclass(frozen=True)
class IndexDef:
    key: str
    name: str
    field: str
    sign: int
    scale: float
    plain: str
    box: Box | None = None
    point_difference: dict[str, dict[str, float]] | None = None
    box_difference: dict[str, Box] | None = None
    sst_minus: bool = False
    units: str = ""
    offset: float = 0.0     # value = sign * scale * (raw - offset); e.g. 273.15 for K -> C


def load_indices(config_dir: Path | None = None) -> dict[str, IndexDef]:
    raw = load_yaml("indices", config_dir)["indices"]
    out: dict[str, IndexDef] = {}
    for key, d in raw.items():
        out[key] = IndexDef(
            key=key,
            name=d["name"],
            field=d["field"],
            sign=int(d.get("sign", 1)),
            scale=float(d.get("scale", 1.0)),
            plain=d.get("plain", key),
            box=Box.from_dict(d["box"]) if "box" in d else None,
            point_difference=d.get("point_difference"),
            box_difference=(
                {k: Box.from_dict(v) for k, v in d["box_difference"].items()}
                if "box_difference" in d else None
            ),
            sst_minus=bool(d.get("sst_minus", False)),
            units=d.get("units", ""),
            offset=float(d.get("offset", 0.0)),
        )
    return out


@dataclass(frozen=True)
class SnowConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "SnowConfig":
        return cls(raw=load_yaml("snow", config_dir))

    @property
    def mask(self) -> Box:
        return Box.from_dict(self.raw["snow_w"]["mask"])

    @property
    def training_months(self) -> tuple[int, ...]:
        return tuple(int(m) for m in self.raw["season"]["training_months"])

    @property
    def scoring_months(self) -> tuple[int, ...]:
        return tuple(int(m) for m in self.raw["season"]["scoring_months"])
