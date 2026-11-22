"""Data access from the Microsoft Planetary Computer STAC API (no account or key needed).

* Sentinel-2 L2A: monthly cloud-masked median composites.
* Sentinel-1 RTC: monthly mean backscatter (gamma0) per polarization, averaged in linear power.
* USGS 3DEP lidar height above ground (2 m): aggregated to the 10 m grid.
* USGS GAP/LANDFIRE 2011 ecological systems and NAIP 60 cm photos for checks.

Results are cached as GeoTIFFs in ``data/`` so reruns are fast.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

S2_BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
# Scene Classification Layer values kept as "clear": 2 dark area, 4 vegetation, 5 bare soil,
# 6 water, 7 unclassified. Dropped: 0 no data, 1 saturated, 3 cloud shadow, 8/9 cloud, 10 cirrus, 11 snow.
CLEAR_SCL = (2, 4, 5, 6, 7)
LOAD_THREADS = int(os.environ.get("BRUSHMAP_LOAD_THREADS", "8")) or None
HAG_MAX_M = 30.0  # heights above this are treated as noise (towers, birds, bad returns)


@dataclass
class Grid:
    """Pixel grid shared by every raster in a run."""

    crs: str
    transform: tuple  # affine coefficients (a, b, c, d, e, f)
    shape: tuple  # (rows, cols)
    resolution: float


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def make_grid(bbox, epsg: int, resolution: float) -> Grid:
    """Grid aligned to whole multiples of ``resolution`` that covers the WGS 84 ``bbox``."""
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, epsg, always_xy=True)
    xs, ys = tr.transform([bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]])
    x0, x1 = np.floor(min(xs) / resolution) * resolution, np.ceil(max(xs) / resolution) * resolution
    y0, y1 = np.floor(min(ys) / resolution) * resolution, np.ceil(max(ys) / resolution) * resolution
    shape = (int(round((y1 - y0) / resolution)), int(round((x1 - x0) / resolution)))
    return Grid(f"EPSG:{epsg}", (resolution, 0.0, float(x0), 0.0, -resolution, float(y1)), shape, resolution)


def geobox(grid: Grid):
    from affine import Affine
    from odc.geo.geobox import GeoBox

    return GeoBox(grid.shape, Affine(*grid.transform), grid.crs)


def catalog():
    import planetary_computer
    import pystac_client

    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


# --------------------------------------------------------------------------- Sentinel-2
def search_sentinel2(bbox, datetime: str, max_cloud: float, max_items: int):
    """Sentinel-2 L2A items of the ``max_items`` least-cloudy acquisition dates in ``datetime``.

    Dates, not single items, are ranked (by their cloudiest tile), and every tile of a chosen date
    is returned, so a box that straddles two MGRS tiles is always covered by both.
    """
    items = list(catalog().search(collections=["sentinel-2-l2a"], bbox=bbox, datetime=datetime,
                                  query={"eo:cloud_cover": {"lt": max_cloud}}).items())
    by_date: dict = {}
    for it in items:
        by_date.setdefault(it.datetime.date(), []).append(it)
    ranked = sorted(by_date, key=lambda d: (max(i.properties["eo:cloud_cover"] for i in by_date[d]), d))
    return [it for d in ranked[:max_items] for it in sorted(by_date[d], key=lambda i: i.id)]


def boa_offset(item) -> float:
    """Processing baseline 04.00+ (from Jan 2022) adds a -1000 DN offset to L2A reflectance."""
    return -1000.0 if float(item.properties.get("s2:processing_baseline", "00.00")) >= 4.0 else 0.0


def s2_composite(items, grid: Grid):
    """Cloud-masked per-pixel median of ``items``. Returns (dict band -> float32 reflectance, clear count)."""
    import odc.stac

    ds = odc.stac.load(items, bands=S2_BANDS + ["SCL"], geobox=geobox(grid), groupby="solar_day",
                       resampling="nearest", dtype="uint16", nodata=0,
                       pool=LOAD_THREADS, progress=None)
    offsets = {np.datetime64(it.datetime.date()): boa_offset(it) for it in items}
    day_offset = np.array([offsets.get(t, 0.0) for t in ds.time.values.astype("datetime64[D]")], "float32")
    clear = np.isin(ds["SCL"].values, CLEAR_SCL)
    bands = {}
    for b in S2_BANDS:
        dn = ds[b].values.astype("float32")
        refl = (dn + day_offset[:, None, None]) / 10000.0
        refl[~(clear & (dn > 0))] = np.nan
        with warnings.catch_warnings():  # pixels never clear in this window are expected
            warnings.simplefilter("ignore", RuntimeWarning)
            bands[b] = np.nanmedian(refl, axis=0).astype("float32")
        del dn, refl
    return bands, clear.sum(axis=0).astype("int16")


# --------------------------------------------------------------------------- Sentinel-1
def search_sentinel1(bbox, datetime: str, orbit_state: str = "ascending", relative_orbit: int | None = None):
    items = list(catalog().search(collections=["sentinel-1-rtc"], bbox=bbox, datetime=datetime,
                                  query={"sat:orbit_state": {"eq": orbit_state}}).items())
    if relative_orbit is not None:
        items = [it for it in items if it.properties.get("sat:relative_orbit") == relative_orbit]
    return sorted(items, key=lambda it: it.datetime)


def s1_orbit_coverage(items, bbox):
    """Dates per relative orbit and the median share of ``bbox`` covered on one date of that orbit."""
    from shapely.geometry import box, shape
    from shapely.ops import unary_union

    aoi = box(*bbox)
    by_date: dict = {}
    for it in items:
        key = (it.properties["sat:relative_orbit"], it.datetime.date())
        by_date.setdefault(key, []).append(shape(it.geometry))
    orbits: dict = {}
    shares: dict = {}
    for (orbit, day), geoms in by_date.items():
        orbits.setdefault(orbit, set()).add(day)
        shares.setdefault(orbit, []).append(unary_union(geoms).intersection(aoi).area / aoi.area)
    return orbits, {o: float(np.median(v)) for o, v in shares.items()}


def s1_mean_linear(items, grid: Grid):
    """Mean gamma0 backscatter per polarization in **linear power** (not dB) and the date count.

    Averaging in linear units and converting to dB afterwards is the correct order: the mean of
    dB values is a geometric mean and is biased low. Averaging several dates also reduces
    speckle (the grainy noise of radar images).
    """
    import odc.stac

    ds = odc.stac.load(items, bands=["vv", "vh"], geobox=geobox(grid), groupby="solar_day",
                       resampling="nearest", dtype="float32", nodata=-32768, pool=LOAD_THREADS, progress=None)
    out = {}
    for b in ("vv", "vh"):
        v = ds[b].values
        v[(v <= 0) | ~np.isfinite(v)] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out[b] = np.nanmean(v, axis=0).astype("float32")
    n = np.isfinite(ds["vh"].values).sum(axis=0).astype("int16")
    return out, n, [str(t)[:10] for t in ds.time.values]


def to_db(linear):
    """10 * log10(linear power); NaN where not positive."""
    linear = np.asarray(linear, dtype="float32")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(linear > 0, 10.0 * np.log10(linear), np.nan).astype("float32")


# --------------------------------------------------------------------------- lidar
def search_hag(bbox):
    return list(catalog().search(collections=["3dep-lidar-hag"], bbox=bbox).items())


def aggregate_height(hag: np.ndarray, factor: int, threshold_m: float = 1.0):
    """Summaries of a fine height raster over ``factor`` x ``factor`` blocks.

    Returns (fraction of cells taller than ``threshold_m``, mean height, max height), NaN where
    the block has no valid cell. ``hag`` uses NaN for no data.
    """
    r, c = hag.shape[0] // factor, hag.shape[1] // factor
    h = hag[: r * factor, : c * factor].reshape(r, factor, c, factor)
    valid = np.isfinite(h)
    n = valid.sum(axis=(1, 3)).astype("float32")
    tall = (np.where(valid, h, 0) > threshold_m).sum(axis=(1, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(n > 0, tall / n, np.nan).astype("float32")
        mean = np.where(n > 0, np.nansum(h, axis=(1, 3)) / n, np.nan).astype("float32")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mx = np.nanmax(h, axis=(1, 3)).astype("float32")
    return frac, mean, mx


def load_height(items, grid: Grid, fine: float = 2.0, tile_px: int = 500, threshold_m: float = 1.0):
    """Lidar height summaries on ``grid``, built tile by tile from the 2 m HAG COGs.

    Each 10 m pixel gets: share of 2 m cells taller than ``threshold_m`` (a woody-cover proxy),
    mean and max height. Tiles keep memory small. Where several lidar projects overlap, the
    tallest valid value is kept.
    """
    import rasterio
    from affine import Affine
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import Resampling, transform_bounds

    factor = int(round(grid.resolution / fine))
    a, _, x0, _, e, y0 = grid.transform
    rows, cols = grid.shape
    out = {k: np.full(grid.shape, np.nan, "float32") for k in ("frac", "mean", "max")}
    srcs = []
    for it in items:
        try:
            src = rasterio.open(it.assets["data"].href)
        except Exception:  # noqa: BLE001 - skip an unreadable tile, report via NaNs
            continue
        b = transform_bounds(src.crs, grid.crs, *src.bounds)
        srcs.append((src, b, it.properties.get("3dep:usgs_id", it.id)))
    used = set()
    for r0 in range(0, rows, tile_px):
        for c0 in range(0, cols, tile_px):
            nr, nc = min(tile_px, rows - r0), min(tile_px, cols - c0)
            tx0, ty0 = x0 + c0 * a, y0 + r0 * e
            tb = (tx0, ty0 + nr * e, tx0 + nc * a, ty0)
            fine_t = Affine(fine, 0, tx0, 0, -fine, ty0)
            acc = np.full((nr * factor, nc * factor), np.nan, "float32")
            for src, b, pid in srcs:
                if b[0] > tb[2] or b[2] < tb[0] or b[1] > tb[3] or b[3] < tb[1]:
                    continue
                with WarpedVRT(src, crs=grid.crs, transform=fine_t, width=nc * factor, height=nr * factor,
                               resampling=Resampling.nearest, nodata=src.nodata) as vrt:
                    arr = vrt.read(1).astype("float32")
                arr[(arr == src.nodata) | (arr < 0) | (arr > HAG_MAX_M)] = np.nan
                if np.isfinite(arr).any():
                    used.add(pid)
                acc = np.fmax(acc, arr)
            f, m, x = aggregate_height(acc, factor, threshold_m)
            out["frac"][r0 : r0 + nr, c0 : c0 + nc] = f
            out["mean"][r0 : r0 + nr, c0 : c0 + nc] = m
            out["max"][r0 : r0 + nr, c0 : c0 + nc] = x
    for src, _, _ in srcs:
        src.close()
    return out, sorted(used)


# --------------------------------------------------------------------------- GAP and NAIP
def load_gap(bbox, grid: Grid):
    """GAP/LANDFIRE 2011 ecological-system codes on ``grid`` (nearest neighbour) and the class names."""
    import odc.stac

    cat = catalog()
    items = list(cat.search(collections=["gap"], bbox=bbox).items())
    ds = odc.stac.load(items, bands=["data"], geobox=geobox(grid), resampling="nearest", dtype="int16",
                       nodata=0, pool=LOAD_THREADS, progress=None)
    vals = cat.get_collection("gap").extra_fields["item_assets"]["data"]["file:values"]
    names = {v["values"][0]: v["summary"] for v in vals}
    return ds["data"].values.max(axis=0), names, [it.id for it in items]


def load_naip(x_center, y_center, half_m, epsg: int, year: int):
    """RGB(+NIR) NAIP window around a point (map units of ``epsg``) at 0.6 m. Returns (array, extent, item id)."""
    import rasterio
    from affine import Affine
    from pyproj import Transformer
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import Resampling

    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(x_center, y_center)
    items = list(catalog().search(collections=["naip"], intersects={"type": "Point", "coordinates": [lon, lat]},
                                  datetime=f"{year}-01-01/{year}-12-31").items())
    if not items:
        return None, None, None
    it = items[0]
    res = 0.6
    n = int(round(2 * half_m / res))
    t = Affine(res, 0, x_center - half_m, 0, -res, y_center + half_m)
    with rasterio.open(it.assets["image"].href) as src, WarpedVRT(
        src, crs=f"EPSG:{epsg}", transform=t, width=n, height=n, resampling=Resampling.bilinear
    ) as vrt:
        arr = vrt.read()
    extent = (x_center - half_m, x_center + half_m, y_center - half_m, y_center + half_m)
    return arr, extent, it.id


# --------------------------------------------------------------------------- caching
def save_stack(path: Path, arrays: np.ndarray, names: list[str], grid: Grid, nodata=np.nan):
    import rasterio
    from affine import Affine

    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = np.asarray(arrays)
    if arrays.ndim == 2:
        arrays = arrays[None]
    profile = dict(driver="GTiff", height=grid.shape[0], width=grid.shape[1], count=arrays.shape[0],
                   dtype=arrays.dtype.name, crs=grid.crs, transform=Affine(*grid.transform),
                   compress="deflate", tiled=True, nodata=nodata, BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arrays)
        for i, n in enumerate(names, start=1):
            dst.set_band_description(i, n)


def read_stack(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        arr = src.read()
        names = list(src.descriptions)
        t = src.transform
        grid = Grid(src.crs.to_string(), (t.a, t.b, t.c, t.d, t.e, t.f), (src.height, src.width), abs(t.a))
    return arr, names, grid


def configure_gdal():
    """Point GDAL at its data files when the conda env was not activated, and make HTTP reads
    time out and retry instead of stalling on a dropped connection."""
    for key, value in {"GDAL_HTTP_TIMEOUT": "60", "GDAL_HTTP_MAX_RETRY": "5", "GDAL_HTTP_RETRY_DELAY": "2",
                       "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}.items():
        os.environ.setdefault(key, value)
    if "GDAL_DATA" not in os.environ:
        import sys

        for cand in (Path(sys.prefix) / "Library" / "share" / "gdal", Path(sys.prefix) / "share" / "gdal"):
            if cand.exists():
                os.environ["GDAL_DATA"] = str(cand)
                break
    if "PROJ_DATA" not in os.environ:
        import sys

        for cand in (Path(sys.prefix) / "Library" / "share" / "proj", Path(sys.prefix) / "share" / "proj"):
            if cand.exists():
                os.environ["PROJ_DATA"] = str(cand)
                break
