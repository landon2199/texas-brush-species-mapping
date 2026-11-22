"""Reference labels: TPWD Ecological Mapping Systems of Texas (EMST) and USGS GAP/LANDFIRE 2011.

EMST polygons are read from TPWD's public ArcGIS REST map service (no login), clipped to the
study box by the query, and burned onto the analysis grid. Each EMST type is assigned to one of
six analysis classes by the keyword rules in :func:`emst_class`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

EMST_SERVICE = (
    "https://tpwd.texas.gov/server/rest/services/Vegetation_Mapping/"
    "Texas_Ecological_Mapping_Systems_Data_2020/MapServer"
)
EMST_LAYERS = tuple(range(1, 12))  # one layer per ecoregion; only those that intersect the box return data

# Analysis classes: code -> (name, color)
CLASSES = {
    1: ("Mesquite shrubland", "#c8a03c"),
    2: ("Grassland", "#e8e07a"),
    3: ("Juniper / evergreen woody", "#1f5f3a"),
    4: ("Deciduous woody (oak, riparian)", "#6fa35a"),
    5: ("Cropland", "#d77fb3"),
    6: ("Other (urban, water, barren)", "#8a8a8a"),
}
MESQUITE = 1


def emst_class(name: str) -> int:
    """Map an EMST common name to an analysis class (rules are checked in order).

    1 mesquite: any type with "mesquite" in its name (e.g. "Native Invasive: Mesquite Shrubland").
    5 cropland: "Row Crops".
    6 other: urban, barren, open water, marsh, quarries.
    3 juniper/evergreen woody: juniper, evergreen, live oak types.
    2 grassland: prairie, grassland, herbaceous vegetation, savanna grassland.
    4 deciduous woody: remaining forest, woodland and shrubland types (post oak, shin oak,
      floodplain and riparian hardwoods, deciduous shrublands).
    Anything else -> 0 (excluded).
    """
    n = name.lower()
    if "mesquite" in n:
        return 1
    if "row crop" in n:
        return 5
    if n.startswith("urban") or any(k in n for k in ("barren", "open water", "marsh", "quarry", "swamp")):
        return 6
    if any(k in n for k in ("juniper", "evergreen", "live oak", "redcedar")):
        return 3
    if any(k in n for k in ("prairie", "grassland", "herbaceous", "savanna grass", "tobosa", "grama", "grass farm")):
        return 2
    if any(k in n for k in ("forest", "woodland", "shrubland", "deciduous", "shrub", "oak")):
        return 4
    return 0


# USGS GAP/LANDFIRE 2011 ecological systems -> analysis classes (used only as a second opinion).
def gap_class(name: str) -> int:
    n = name.lower()
    if "mesquite" in n:
        return 1
    if "cultivated cropland" in n:
        return 5
    if any(k in n for k in ("developed", "open water", "barren", "quarr")):
        return 6
    if any(k in n for k in ("juniper", "live oak", "evergreen")):
        return 3
    if any(k in n for k in ("prairie", "grassland", "pasture/hay", "steppe", "herbaceous")):
        return 2
    if any(k in n for k in ("forest", "woodland", "shrubland", "savanna", "riparian", "floodplain", "shrub")):
        return 4
    return 0


def _get_json(url: str, params: dict, retries: int = 4) -> dict:
    import requests

    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception:  # noqa: BLE001 - retry transient network errors
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_emst(bbox, epsg: int, cache: Path) -> dict:
    """GeoJSON FeatureCollection of EMST polygons intersecting ``bbox`` (WGS 84), in EPSG ``epsg``.

    Cached in ``cache`` so the TPWD server is queried once.
    """
    if cache.exists():
        return json.loads(cache.read_text())
    envelope = ",".join(str(v) for v in bbox)
    features = []
    for layer in EMST_LAYERS:
        base = f"{EMST_SERVICE}/{layer}/query"
        common = dict(geometry=envelope, geometryType="esriGeometryEnvelope", inSR=4326,
                      spatialRel="esriSpatialRelIntersects")
        n = _get_json(base, {**common, "where": "1=1", "returnCountOnly": "true", "f": "json"}).get("count", 0)
        offset = 0
        while offset < n:
            page = _get_json(base, {**common, "where": "1=1", "outFields": "Veg_ID,CommonName,EcoRegion",
                                    "outSR": epsg, "returnGeometry": "true", "resultOffset": offset,
                                    "resultRecordCount": 1000, "orderByFields": "OBJECTID", "f": "geojson"})
            got = page.get("features", [])
            for f in got:
                f["properties"]["layer"] = layer
            features.extend(got)
            if not got:
                break
            offset += len(got)
    fc = {"type": "FeatureCollection", "features": features, "crs_epsg": epsg}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(fc))
    return fc


def rasterize_emst(fc: dict, shape, transform):
    """Burn EMST ``Veg_ID`` codes onto the grid. Returns (veg_id array int16, {veg_id: name})."""
    from affine import Affine
    from rasterio.features import rasterize

    names, shapes = {}, []
    for f in fc["features"]:
        vid = int(f["properties"]["Veg_ID"])
        names[vid] = f["properties"]["CommonName"]
        if f.get("geometry"):
            shapes.append((f["geometry"], vid))
    veg = rasterize(shapes, out_shape=shape, transform=Affine(*transform), fill=0, dtype="int16")
    return veg, names


def to_classes(codes: np.ndarray, names: dict, rule=emst_class):
    """Recode a raster of source codes into analysis classes. Returns (classes uint8, table)."""
    out = np.zeros(codes.shape, dtype="uint8")
    table = {}
    for code, name in names.items():
        cls = rule(name)
        table[int(code)] = (name, cls)
        if cls:
            out[codes == code] = cls
    return out, table
