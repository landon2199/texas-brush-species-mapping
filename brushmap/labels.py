"""Reference labels: TPWD Ecological Mapping Systems of Texas (EMST) and USGS GAP/LANDFIRE 2011.

EMST polygons are read from TPWD's public ArcGIS REST map service (no login), clipped to the
study box by the query, and burned onto the analysis grid. Each EMST type is assigned to an
analysis class by keyword rules: :func:`emst_class_juniper` for the Ashe juniper site and
:func:`emst_class` for the mesquite site.
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

# Analysis classes per study site: code -> (name, color). Colors checked with a colorblind-safety
# validator: every pair of classes stays distinct under protan, deutan and tritan vision. ``CLASSES`` holds the active site's table
# (set by :func:`set_site`); the figures read it.
MESQUITE_CLASSES = {
    1: ("Mesquite shrubland", "#eb6834"),
    2: ("Grassland", "#e8e07a"),
    3: ("Juniper / evergreen woody", "#1f5f3a"),
    4: ("Deciduous woody (oak, riparian)", "#3d9e8c"),
    5: ("Cropland", "#a8458f"),
    6: ("Other (urban, water, barren)", "#b0b0b0"),
}
JUNIPER_CLASSES = {
    1: ("Ashe juniper", "#1f5f3a"),
    2: ("Grassland", "#e8e07a"),
    3: ("Other woody (oak, mesquite, riparian)", "#3d9e8c"),
    4: ("Cropland / other (urban, water, barren)", "#a8458f"),
}
CLASSES = dict(MESQUITE_CLASSES)
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


_OTHER_COVER = ("barren", "open water", "marsh", "quarry", "swamp")
_GRASS = ("prairie", "grassland", "herbaceous", "savanna grass", "tobosa", "grama", "grass farm", "pasture/hay",
          "steppe")
_WOODY = ("forest", "woodland", "shrubland", "shrub", "motte", "oak", "savanna")
_OTHER_TAXA = ("oak", "hardwood", "deciduous", "mesquite", "elm", "pecan", "cypress", "sycamore", "cottonwood",
               "willow", "persimmon", "pine", "evergreen", "hackberry", "walnut")


def juniper_first(name: str) -> bool:
    """True when juniper (or redcedar) is the first woody plant named in the type.

    EMST names list the dominant plants first, e.g. "Ashe Juniper - Live Oak Shrubland" (juniper
    first) vs "Oak / Ashe Juniper Slope Forest" (oak first). Setting words such as "Riparian" or
    "Floodplain" are not plants and are ignored.
    """
    t = name.lower().split(":")[-1]
    j = min((t.find(k) for k in ("juniper", "redcedar") if k in t), default=-1)
    if j < 0:
        return False
    others = [t.find(k) for k in _OTHER_TAXA if k in t]
    return not others or j < min(others)


def emst_class_juniper(name: str) -> int:
    """EMST type -> Ashe juniper site classes (rules checked in order).

    4 cropland / other: row crops, urban, barren, water, marsh, quarries.
    1 Ashe juniper: juniper is the first plant named (includes juniper - live oak mixes).
    2 grassland: prairie, grassland, herbaceous and savanna grassland types.
    3 other woody: remaining forest, woodland, shrubland and motte types (oaks, mesquite,
      riparian hardwoods, and mixes where an oak or hardwood is named before juniper).
    """
    n = name.lower()
    if "row crop" in n or n.startswith("urban") or any(k in n for k in _OTHER_COVER):
        return 4
    if juniper_first(n):
        return 1
    if any(k in n for k in _GRASS):
        return 2
    if any(k in n for k in _WOODY + ("juniper", "mesquite", "deciduous")):
        return 3
    return 0


def gap_class_juniper(name: str) -> int:
    n = name.lower()
    if any(k in n for k in ("cultivated cropland", "developed", "open water", "barren", "quarr")):
        return 4
    if juniper_first(n):
        return 1
    if any(k in n for k in _GRASS):
        return 2
    if any(k in n for k in _WOODY + ("riparian", "floodplain", "juniper", "mesquite")):
        return 3
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


# Study sites. ``target`` is the species class; ``grass`` and ``woody`` drive the lidar checks;
# ``curves`` are the classes drawn in the hero greenness panel; ``checks`` the NAIP spot-check classes.
SITES = {
    "juniper": {
        "classes": JUNIPER_CLASSES, "emst_rule": emst_class_juniper, "gap_rule": gap_class_juniper,
        "target": 1, "grass": 2, "woody": (1, 3), "curves": (1, 2, 3, 4), "checks": (1, 3, 2),
        "bbox": [-99.26, 29.95, -99.00, 30.175], "place": "Hill Country around Kerrville, Texas",
        "species": "Ashe juniper (Juniperus ashei)",
    },
    "mesquite": {
        "classes": MESQUITE_CLASSES, "emst_rule": emst_class, "gap_rule": gap_class,
        "target": 1, "grass": 2, "woody": (1, 3, 4), "curves": (1, 2, 3, 5), "checks": (1, 2, 3),
        "bbox": [-99.95, 32.0, -99.68, 32.225], "place": "Rolling Plains south of Abilene, Texas",
        "species": "honey mesquite (Prosopis glandulosa)",
    },
}


def set_site(site: str) -> dict:
    """Make ``site`` the active study site (updates ``CLASSES`` in place) and return its settings."""
    cfg = SITES[site]
    CLASSES.clear()
    CLASSES.update(cfg["classes"])
    return cfg
