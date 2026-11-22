"""Build (and cache) every input raster on one 10 m grid.

The inputs come in four independent parts (labels, Sentinel-2, Sentinel-1, lidar). ``run.py``
builds each part in its own process, in parallel: on Windows, GDAL network reads were seen to
stall thread pools used later in the same process (see sentinel2-landcover-ml), and parallel
parts cut the first-run time.
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import numpy as np

from . import data, features, labels

SEASON_PARTS = tuple(features.SEASONS)  # DJF uses Jan, Feb and Dec of the same year
PARTS = ("labels", "lidar") + tuple(f"s2_{s}" for s in SEASON_PARTS) + tuple(f"s1_{s}" for s in SEASON_PARTS)
S2_INDICES = ("NDVI", "NDRE", "NDMI")


def feature_names() -> list[str]:
    """All model features in their fixed order."""
    names = [f"S2_m{m:02d}_{i}" for m in features.MONTHS for i in S2_INDICES]
    names += [f"S2_{s}_{b}" for s in features.SEASONS for b in data.S2_BANDS]
    names += [f"S1_m{m:02d}_{p}" for m in features.MONTHS for p in ("VV", "VH", "VHVV")]
    return names + ["LIDAR_frac1m", "LIDAR_mean", "LIDAR_max"]


def part_names(part: str) -> list[str]:
    """Layers stored in one cached part (Sentinel parts hold one season each)."""
    if part == "labels":
        return ["emst_class", "emst_veg_id", "gap_class", "gap_code"]
    if part == "lidar":
        return ["LIDAR_frac1m", "LIDAR_mean", "LIDAR_max"]
    sensor, season = part.split("_")
    months = sorted(features.SEASONS[season])
    if sensor == "s2":
        return [f"S2_m{m:02d}_{i}" for m in months for i in S2_INDICES] + [f"S2_{season}_{b}" for b in data.S2_BANDS]
    if sensor == "s1":
        return [f"S1_m{m:02d}_{p}" for m in months for p in ("VV", "VH", "VHVV")]
    raise ValueError(part)


def part_paths(cache: Path, tag: str, part: str) -> tuple[Path, Path]:
    return cache / f"{part}_{tag}.tif", cache / f"{part}_{tag}.json"


def _log(part, msg, t0):
    print(f"[{part:6s} {time.time() - t0:5.0f} s] {msg}", flush=True)


def build_part(part: str, bbox, year: int, resolution: float, cache: Path, tag: str,
               max_cloud: float = 60.0, s2_per_month: int = 4, s1_orbit: int | None = None) -> dict:
    """Download, composite and cache one part. Returns its metadata dict."""
    t0 = time.time()
    data.configure_gdal()
    tif, meta_path = part_paths(cache, tag, part)
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    epsg = data.utm_epsg(lon, lat)
    grid = data.make_grid(bbox, epsg, resolution)
    names = part_names(part)
    pos = {n: k for k, n in enumerate(names)}
    meta = {"crs": grid.crs, "grid_shape": list(grid.shape)}
    stack = np.full((len(names),) + tuple(grid.shape), np.nan, dtype="float32")
    _log(part, f"grid {grid.shape} at {resolution:g} m, {len(names)} layers", t0)

    if part == "labels":
        # EMST (main reference) and GAP/LANDFIRE 2011 (second opinion)
        fc = labels.fetch_emst(bbox, epsg, cache / f"emst_{tag}.geojson")
        veg, veg_names = labels.rasterize_emst(fc, grid.shape, grid.transform)
        emst_cls, emst_table = labels.to_classes(veg, veg_names, labels.emst_class)
        gap_codes, gap_names, gap_items = data.load_gap(bbox, grid)
        present = {int(c): gap_names.get(int(c), "?") for c in np.unique(gap_codes) if c > 0}
        gap_cls, gap_table = labels.to_classes(gap_codes, present, labels.gap_class)
        meta["emst"] = {"n_polygons": len(fc["features"]), "types": {
            str(k): {"name": v[0], "class": v[1], "share": round(float((veg == k).mean()), 5)}
            for k, v in sorted(emst_table.items(), key=lambda kv: -(veg == kv[0]).sum())}}
        meta["gap"] = {"items": gap_items, "types": {
            str(k): {"name": v[0], "class": v[1], "share": round(float((gap_codes == k).mean()), 5)}
            for k, v in sorted(gap_table.items(), key=lambda kv: -(gap_codes == kv[0]).sum())}}
        stack = np.stack([emst_cls, veg, gap_cls, gap_codes]).astype("int16")
        _log(part, f"{len(fc['features'])} EMST polygons, {len(present)} GAP systems", t0)

    elif part.startswith("s2_"):
        season = part.split("_")[1]
        held, s2_meta = {}, {}
        for m in sorted(features.SEASONS[season]):
            start = np.datetime64(f"{year}-{m:02d}-01")
            end = (start.astype("datetime64[M]") + 1).astype("datetime64[D]") - 1
            window = f"{start}/{end}"
            items = data.search_sentinel2(bbox, window, max_cloud, s2_per_month)
            s2_meta[str(m)] = {"window": window, "items": sorted(it.id for it in items),
                               "cloud_cover": [round(it.properties["eo:cloud_cover"], 1) for it in items]}
            if not items:
                continue
            bands, n_clear = data.s2_composite(items, grid)
            for name, arr in features.spectral_indices(bands).items():
                stack[pos[f"S2_m{m:02d}_{name}"]] = arr
            held[m] = bands
            s2_meta[str(m)]["share_without_clear_observation"] = round(float((n_clear == 0).mean()), 4)
            _log(part, f"{window}: {len(items)} scenes, {100 * (n_clear == 0).mean():.1f}% never clear", t0)
        if held:  # seasonal median of each band over the months of the season
            for b in data.S2_BANDS:
                stack[pos[f"S2_{season}_{b}"]] = features.season_median({x: held[x][b] for x in held}, season)
        meta["months"] = s2_meta

    elif part.startswith("s1_"):
        season = part.split("_")[1]
        all_s1 = data.search_sentinel1(bbox, f"{year}-01-01/{year}-12-31", "ascending")
        orbits, cover = data.s1_orbit_coverage(all_s1, bbox)
        # Same choice in every seasonal part: the ascending orbit whose typical date covers most of
        # the box (a swath edge can cut a box), then the one with the most dates.
        orbit = s1_orbit or max(sorted(orbits), key=lambda o: (round(cover[o], 2), len(orbits[o])))
        meta.update({"orbit_state": "ascending", "relative_orbit": int(orbit),
                     "dates_per_orbit": {str(o): len(d) for o, d in orbits.items()},
                     "median_box_coverage_per_orbit": {str(o): round(c, 3) for o, c in cover.items()}, "months": {}})
        for m in sorted(features.SEASONS[season]):
            items = [it for it in all_s1 if it.properties["sat:relative_orbit"] == orbit and it.datetime.month == m]
            if not items:
                continue
            lin, n, dates = data.s1_mean_linear(items, grid)
            vv, vh = data.to_db(lin["vv"]), data.to_db(lin["vh"])
            stack[pos[f"S1_m{m:02d}_VV"]] = vv
            stack[pos[f"S1_m{m:02d}_VH"]] = vh
            stack[pos[f"S1_m{m:02d}_VHVV"]] = vh - vv  # ratio in dB = difference of dB values
            meta["months"][str(m)] = {"dates": dates, "items": sorted(it.id for it in items),
                                      "share_without_data": round(float((n == 0).mean()), 4)}
            _log(part, f"{year}-{m:02d}: {len(dates)} dates", t0)

    elif part == "lidar":
        hag_items = data.search_hag(bbox)
        height, projects = data.load_height(hag_items, grid)
        stack[pos["LIDAR_frac1m"]] = height["frac"]
        stack[pos["LIDAR_mean"]] = height["mean"]
        stack[pos["LIDAR_max"]] = height["max"]
        meta.update({"items": len(hag_items), "projects": projects,
                     "share_without_lidar": round(float(np.isnan(height["frac"]).mean()), 4)})
        _log(part, f"{len(hag_items)} tiles from {len(projects)} projects", t0)

    data.save_stack(tif, stack, names, grid, nodata=-1 if part == "labels" else np.nan)
    meta["seconds"] = round(time.time() - t0, 1)
    meta_path.write_text(json.dumps(meta, indent=1))
    _log(part, "cached", t0)
    return meta


def load_inputs(cache: Path, tag: str):
    """Read the cached parts into one feature stack and fill gaps.

    Gap filling: monthly series (S2 indices, S1 backscatter) are interpolated in time over a
    circular year; a seasonal band median with no clear view of a pixel takes that band's median
    over the other seasons. Returns (stack, names, label stack, label names, grid, meta).
    """
    import rasterio

    names = feature_names()
    pos = {n: k for k, n in enumerate(names)}
    tif, mp = part_paths(cache, tag, "labels")
    lab, lab_names, grid = data.read_stack(tif)
    meta = {"labels": json.loads(mp.read_text())}
    stack = np.empty((len(names),) + tuple(grid.shape), dtype="float32")
    for part in PARTS[1:]:
        tif, mp = part_paths(cache, tag, part)
        meta[part] = json.loads(mp.read_text())
        with rasterio.open(tif) as src:
            assert list(src.descriptions) == part_names(part), f"{part}: cached band names differ"
            for i, n in enumerate(part_names(part), start=1):
                stack[pos[n]] = src.read(i)
    filled = {}
    for var in [("S2", i) for i in S2_INDICES] + [("S1", p) for p in ("VV", "VH", "VHVV")]:
        rows = [pos[f"{var[0]}_m{m:02d}_{var[1]}"] for m in features.MONTHS]
        stack[rows], n = features.fill_circular(stack[rows])
        filled[f"{var[0]} {var[1]}"] = round(n / (12 * stack[0].size), 5)
    seasonal_filled = 0
    for b in data.S2_BANDS:
        rows = [pos[f"S2_{s}_{b}"] for s in features.SEASONS]
        block = stack[rows]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(block, axis=0)
        miss = ~np.isfinite(block)
        seasonal_filled += int(miss.sum())
        stack[rows] = np.where(miss, med[None], block)
    meta["gap_filling"] = {"share_of_pixel_months_filled": filled,
                           "share_of_seasonal_band_values_filled": round(seasonal_filled / (40 * stack[0].size), 6)}
    return stack, names, lab, lab_names, grid, meta
