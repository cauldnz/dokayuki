"""The 1.5-degree lattice, domain selection, area weights and coarsening."""
from __future__ import annotations

import numpy as np
import xarray as xr

from .config import Box

LAT = "latitude"
LON = "longitude"
TARGET = "target"


def lattice(resolution: float = 1.5, lat_origin: float = -90.0, lon_origin: float = 0.0):
    """Global lattice matching the reference repo's ``global1_5`` grid."""
    lats = np.round(np.arange(lat_origin, 90.0 + 1e-9, resolution), 6)
    lons = np.round(np.arange(lon_origin, 360.0 - 1e-9, resolution), 6)
    return lats, lons


def domain_lattice(domain: Box, resolution: float = 1.5):
    lats, lons = lattice(resolution)
    lats = lats[(lats >= domain.lat[0] - 1e-9) & (lats <= domain.lat[1] + 1e-9)]
    lons = lons[(lons >= domain.lon[0] - 1e-9) & (lons <= domain.lon[1] + 1e-9)]
    return lats, lons


def cos_weights(lat: xr.DataArray) -> xr.DataArray:
    w = np.cos(np.deg2rad(np.abs(lat))).astype("float64")
    return w.rename("weights")


def box_mask(lat: xr.DataArray, lon: xr.DataArray, box: Box) -> xr.DataArray:
    """Boolean (lat, lon) mask for a box; longitudes are taken on 0..360."""
    lon360 = lon % 360.0
    lo, hi = box.lon[0] % 360.0, box.lon[1] % 360.0
    in_lon = (lon360 >= lo - 1e-9) & (lon360 <= hi + 1e-9) if lo <= hi else (lon360 >= lo - 1e-9) | (lon360 <= hi + 1e-9)
    in_lat = (lat >= box.lat[0] - 1e-9) & (lat <= box.lat[1] + 1e-9)
    return (in_lat & in_lon).transpose(LAT, LON)


def area_mean(da: xr.DataArray, box: Box, land: xr.DataArray | None = None) -> xr.DataArray:
    """cos(lat)-weighted mean of ``da`` over ``box`` (optionally land-only)."""
    m = box_mask(da[LAT], da[LON], box)
    if box.land_only:
        if land is None:
            raise ValueError("box is land_only but no land mask was given")
        m = m & (land > 0.5)
    w = cos_weights(da[LAT]) * m
    return da.weighted(w.fillna(0.0)).mean((LAT, LON), skipna=True)


def nearest_cell(da: xr.DataArray, lat: float, lon: float) -> xr.DataArray:
    return da.sel({LAT: lat, LON: lon % 360.0}, method="nearest")


def coarsen_block_mean(da: xr.DataArray, factor: int = 6) -> xr.DataArray:
    """Area-mean block coarsening (0.25 -> 1.5 with factor 6), cos(lat)-weighted inside blocks.

    Output cells are centred on the 1.5-degree lattice points (multiples of ``res*factor``);
    the block for lattice point y collects the input cells whose centres lie in
    [y - coarse/2, y + coarse/2). For ERA5 0.25 that is 6 cells per block in each direction
    except at the poles.
    """
    da = da.sortby(LAT).sortby(LON)
    res = float(abs(float(da[LAT][1]) - float(da[LAT][0])))
    coarse = res * factor
    lat_bins = np.floor((da[LAT].values + coarse / 2.0) / coarse) * coarse
    lon_bins = (np.floor((da[LON].values + coarse / 2.0) / coarse) * coarse) % 360.0
    w = cos_weights(da[LAT])
    da = da.assign_coords(lat_bin=(LAT, lat_bins), lon_bin=(LON, lon_bins))
    wda = (da * w)
    num = wda.groupby("lat_bin").sum(LAT, skipna=False).groupby("lon_bin").sum(LON, skipna=False)
    den = (xr.ones_like(da) * w).groupby("lat_bin").sum(LAT).groupby("lon_bin").sum(LON)
    out = (num / den).rename({"lat_bin": LAT, "lon_bin": LON})
    return out


def stack_targets(da: xr.DataArray) -> xr.DataArray:
    """(…, lat, lon) -> (…, target) with a MultiIndex target = (latitude, longitude)."""
    return da.stack({TARGET: (LAT, LON)})


def unstack_targets(da: xr.DataArray) -> xr.DataArray:
    return da.unstack(TARGET)


def as_targets(da: xr.DataArray) -> xr.DataArray:
    """Make sure the last dimension is ``target`` (scalar series get a length-1 axis)."""
    if TARGET in da.dims:
        return da
    if LAT in da.dims and LON in da.dims:
        return stack_targets(da)
    return da.expand_dims({TARGET: [da.name or "index"]})
