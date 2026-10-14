"""Land masks and scoring masks on the 1.5-degree lattice."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from .config import Box, RegionConfig
from .grid import LAT, LON, box_mask


def load_lsm(path: Path) -> xr.DataArray:
    return xr.open_dataarray(path).load()


def scoring_mask(lsm: xr.DataArray, box: Box) -> xr.DataArray:
    """Boolean (lat, lon) mask: inside box and (if land_only) land fraction > 0.5."""
    m = box_mask(lsm[LAT], lsm[LON], box)
    if box.land_only:
        m = m & (lsm > 0.5)
    return m.rename("mask")


def all_scoring_masks(lsm: xr.DataArray, cfg: RegionConfig) -> dict[str, xr.DataArray]:
    return {name: scoring_mask(lsm, box) for name, box in cfg.masks.items()}
