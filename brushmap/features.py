"""Spectral indices, temporal gap filling and the per-pixel feature stack.

Feature names encode the sensor and time so they can be grouped later:
``S2_m04_NDVI`` (Sentinel-2, April), ``S2_MAM_B05`` (Sentinel-2 spring band median),
``S1_m04_VH`` (Sentinel-1, April, dB), ``LIDAR_frac1m`` (lidar).
"""
from __future__ import annotations

import warnings

import numpy as np

MONTHS = list(range(1, 13))
SEASONS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def season_of(month: int) -> str:
    return next(s for s, ms in SEASONS.items() if month in ms)


def normalized_difference(a, b):
    """(a - b) / (a + b), NaN where the denominator is zero or an input is missing."""
    a = np.asarray(a, dtype="float32")
    b = np.asarray(b, dtype="float32")
    den = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / den
    return np.where(den == 0, np.nan, out).astype("float32")


def spectral_indices(bands: dict) -> dict:
    """NDVI = (B08-B04)/(B08+B04)   greenness (Rouse et al. 1974)
    NDRE = (B8A-B05)/(B8A+B05)      red-edge index, more sensitive to chlorophyll in dense canopies
                                    (red-edge normalized difference after Gitelson & Merzlyak 1994)
    NDMI = (B8A-B11)/(B8A+B11)      canopy water (Gao 1996)
    """
    return {
        "NDVI": normalized_difference(bands["B08"], bands["B04"]),
        "NDRE": normalized_difference(bands["B8A"], bands["B05"]),
        "NDMI": normalized_difference(bands["B8A"], bands["B11"]),
    }


def fill_circular(series: np.ndarray, chunk: int = 400_000) -> tuple[np.ndarray, int]:
    """Fill NaNs along axis 0 of a 12-month stack by linear interpolation in time.

    The year is treated as circular (December is next to January), so a missing January is
    interpolated between December and February. Pixels with no valid month stay NaN.
    Works on column chunks to keep memory small. Returns (filled array, number of values filled).
    """
    s = np.array(series, dtype="float32", copy=True)
    t = s.shape[0]
    flat = s.reshape(t, -1)
    filled = 0
    for c0 in range(0, flat.shape[1], chunk):
        block = flat[:, c0 : c0 + chunk]
        ok = np.isfinite(block)
        miss = ~ok & ok.any(axis=0)[None, :]
        if not miss.any():
            continue
        # Repeat three times so "previous" and "next" valid months wrap around the year.
        ok3 = np.concatenate([ok, ok, ok])
        pos = np.arange(3 * t)[:, None]
        prev = np.maximum.accumulate(np.where(ok3, pos, -1), axis=0)[t : 2 * t]
        nxt = np.minimum.accumulate(np.where(ok3, pos, 10 * t)[::-1], axis=0)[::-1][t : 2 * t]
        cols = np.broadcast_to(np.arange(block.shape[1]), block.shape)
        vals3 = np.concatenate([block, block, block])
        pv = vals3[np.clip(prev, 0, 3 * t - 1), cols]
        qv = vals3[np.clip(nxt, 0, 3 * t - 1), cols]
        here = np.arange(t, 2 * t)[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.where(nxt > prev, (here - prev) / (nxt - prev), 0.0)
        interp = (pv + w * (qv - pv)).astype("float32")
        block[miss] = interp[miss]
        filled += int(miss.sum())
    return flat.reshape(s.shape), filled


def season_median(monthly: dict[int, np.ndarray], season: str) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(np.stack([monthly[m] for m in SEASONS[season]]), axis=0).astype("float32")


def config_columns(names: list[str], config: str) -> list[int]:
    """Column indices of the features used by a sensor configuration."""
    want = {
        "S2 only": ("S2_",),
        "S1 only": ("S1_",),
        "S1 + S2": ("S1_", "S2_"),
        "S1 + S2 + lidar": ("S1_", "S2_", "LIDAR_"),
        "lidar only": ("LIDAR_",),
    }[config]
    return [k for k, n in enumerate(names) if n.startswith(want)]
