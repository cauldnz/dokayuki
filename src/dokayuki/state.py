"""The state store: everything the daily run needs, reduced to weekly values.

Layout under ``state/`` (Zarr/NetCDF for arrays, Parquet/JSON for tables):

    era5_15_daily.zarr          daily 1.5-degree domain fields (bootstrap history)
    lsm_15.nc                   land-sea mask on the domain lattice
    truth_weekly.zarr           weekly truth: grid cells (field, time, lat, lon) and indices (time, target)
    snow_w_daily.parquet        daily SNOW-W (m w.e.) over the mask at 0.25 deg
    obs_predictors.parquet      daily AO, MJO features, SoJ SST anomaly, u10 60N, recent snow
    members/<origin>/<lead>/    weekly member values per target: forecasts (issue, member, target)
                                and reforecasts (issue, hyear, member, target)
    requests.json               ECDS request ids (resumable fetches)
    manifest.json               what is stored, with the last dates per component
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import xarray as xr


@dataclass
class State:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {}

    def update_manifest(self, **kv) -> None:
        m = self.manifest()
        m.update({k: (str(v) if isinstance(v, (pd.Timestamp,)) else v) for k, v in kv.items()})
        self.manifest_path.write_text(json.dumps(m, indent=1, sort_keys=True))

    # ---- arrays
    def era5_daily(self) -> xr.Dataset:
        return xr.open_zarr(self.root / "era5_15_daily.zarr", consolidated=False)

    def write_weekly(self, name: str, ds: xr.Dataset) -> Path:
        p = self.root / f"{name}.zarr"
        for v in list(ds.data_vars) + list(ds.coords):
            ds[v].encoding = {}
        ds.to_zarr(p, mode="w", consolidated=False)
        return p

    def read_weekly(self, name: str) -> xr.Dataset:
        return xr.open_zarr(self.root / f"{name}.zarr", consolidated=False).load()

    # ---- tables
    def write_table(self, name: str, df: pd.DataFrame) -> Path:
        p = self.root / f"{name}.parquet"
        df.to_parquet(p)
        return p

    def read_table(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.root / f"{name}.parquet")

    # ---- members
    def members_path(self, origin: str, lead: int, kind: str) -> Path:
        return self.root / "members" / origin / str(lead) / f"{kind}.nc"

    def write_members(self, origin: str, lead: int, kind: str, da: xr.DataArray) -> Path:
        p = self.members_path(origin, lead, kind)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            with xr.open_dataarray(p) as f:
                old = f.load()
            da = xr.concat([old, da], dim="issue")
            da = da.isel(issue=~pd.Index(da["issue"].values).duplicated(keep="last")).sortby("issue")
        da.to_netcdf(p)
        return p

    def read_members(self, origin: str, lead: int, kind: str) -> xr.DataArray | None:
        p = self.members_path(origin, lead, kind)
        return xr.open_dataarray(p).load() if p.exists() else None
