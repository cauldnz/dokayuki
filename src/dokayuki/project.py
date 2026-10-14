"""Project cumulative probabilities onto valid CDFs: non-decreasing in k, within [0, 1]."""
from __future__ import annotations

import numpy as np
import xarray as xr
from sklearn.isotonic import isotonic_regression

from .thresholds import K_DIM, TIME


def project_cdf(P: xr.DataArray) -> xr.DataArray:
    """Isotonic regression across k (unit weights), applied only where the CDF is not monotone.

    NaN CDFs (any k missing) are left untouched, matching the reference projector.
    """
    P = P.transpose(TIME, K_DIM, ...)
    v = np.clip(P.values.copy(), 0.0, 1.0)
    v[np.isnan(P.values)] = np.nan
    flat = v.reshape(v.shape[0], v.shape[1], -1)
    for i in range(flat.shape[0]):
        for g in range(flat.shape[2]):
            c = flat[i, :, g]
            if np.isnan(c).any():
                continue
            if np.any(c[:-1] > c[1:]):
                flat[i, :, g] = isotonic_regression(c, y_min=0.0, y_max=1.0, increasing=True)
    return xr.DataArray(flat.reshape(v.shape), dims=P.dims, coords=P.coords, name=P.name)


def cdf_to_bins(P: xr.DataArray) -> xr.DataArray:
    """Cumulative (k = 1..K-1) -> bin probabilities (bin = 1..K), assuming a projected CDF."""
    P = P.transpose(TIME, K_DIM, ...)
    c = P.values
    full = np.concatenate([np.zeros_like(c[:, :1]), c, np.ones_like(c[:, :1])], axis=1)
    bins = np.diff(full, axis=1)
    coords = {d: P[d] for d in P.dims if d != K_DIM}
    coords["bin"] = np.arange(1, c.shape[1] + 2)
    dims = tuple("bin" if d == K_DIM else d for d in P.dims)
    return xr.DataArray(bins, dims=dims, coords=coords, name="prob")
