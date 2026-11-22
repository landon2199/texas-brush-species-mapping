"""Fast unit tests (no network)."""
import numpy as np
import pytest

from brushmap.assess import error_matrix, feature_groups, olofsson, sample_metrics
from brushmap.data import aggregate_height, to_db
from brushmap.features import config_columns, fill_circular, normalized_difference, spectral_indices
from brushmap.labels import SITES, emst_class, emst_class_juniper, gap_class, gap_class_juniper, juniper_first, set_site
from brushmap.prepare import PARTS, feature_names, part_names
from brushmap.train import block_ids, buffer_zone, clustered_sample, stratified_sample


def test_normalized_difference():
    out = normalized_difference(np.array([0.4, 0.2, 0.0]), np.array([0.1, 0.2, 0.0]))
    assert out[0] == pytest.approx(0.6)
    assert out[1] == pytest.approx(0.0)
    assert np.isnan(out[2])


def test_spectral_indices_leaf_on_vs_leaf_off():
    leaf_on = {"B04": 0.04, "B05": 0.08, "B08": 0.40, "B8A": 0.42, "B11": 0.20}
    bare = {"B04": 0.15, "B05": 0.17, "B08": 0.22, "B8A": 0.23, "B11": 0.30}
    on = spectral_indices({k: np.array(v) for k, v in leaf_on.items()})
    off = spectral_indices({k: np.array(v) for k, v in bare.items()})
    assert on["NDVI"] > 0.7 > off["NDVI"]
    assert on["NDRE"] > off["NDRE"]
    assert on["NDMI"] > 0 > off["NDMI"]


def test_fill_circular_matches_interp_and_wraps():
    s = np.full((12, 2, 2), np.nan, dtype="float32")
    s[:, 0, 0] = np.arange(12)  # complete series: unchanged
    s[[2, 5], 0, 1] = [2.0, 8.0]  # only March and June known
    s[11, 1, 0] = 5.0  # a single valid month fills the whole year
    out, n = fill_circular(s, chunk=1)
    assert np.allclose(out[:, 0, 0], np.arange(12))
    # between March (2) and June (8): April 4, May 6
    assert out[3, 0, 1] == pytest.approx(4.0) and out[4, 0, 1] == pytest.approx(6.0)
    # wrap: June (8) -> March of next year (2) across 9 months; January sits 7 months after June
    assert out[0, 0, 1] == pytest.approx(8 + (2 - 8) * 7 / 9)
    assert np.allclose(out[:, 1, 0], 5.0)
    assert np.isnan(out[:, 1, 1]).all()  # never observed stays NaN
    assert n == 10 + 11


def test_aggregate_height():
    hag = np.zeros((10, 10), dtype="float32")
    hag[:5, :5] = 3.0  # a 10 m shrub in the top-left 5 x 5 block of 2 m cells
    hag[5:, 5:] = np.nan
    hag[0, 9] = 0.5  # short grass tuft does not count as woody
    frac, mean, mx = aggregate_height(hag, 5, threshold_m=1.0)
    assert frac.shape == (2, 2)
    assert frac[0, 0] == 1.0 and frac[0, 1] == 0.0 and frac[1, 0] == 0.0
    assert np.isnan(frac[1, 1]) and np.isnan(mean[1, 1])
    assert mean[0, 0] == pytest.approx(3.0) and mx[0, 1] == pytest.approx(0.5)


def test_db_of_linear_mean_differs_from_mean_of_db():
    lin = np.array([0.01, 0.1], dtype="float32")  # -20 dB and -10 dB
    assert to_db(lin.mean()) == pytest.approx(10 * np.log10(0.055), abs=1e-4)
    assert to_db(lin).mean() == pytest.approx(-15.0)
    assert to_db(lin.mean()) > to_db(lin).mean()  # averaging dB biases backscatter low
    assert np.isnan(to_db(np.array([0.0, -1.0]))).all()


@pytest.mark.parametrize("name, cls", [
    ("Native Invasive: Mesquite Shrubland", 1),
    ("High Plains: Mesquite Shrubland", 1),
    ("Southwest: Tobosa / Mesquite Shrubland", 1),
    ("Rolling Plains: Mixedgrass Prairie", 2),
    ("Edwards Plateau: Floodplain Herbaceous Vegetation", 2),
    ("Blackland Prairie: Disturbance or Tame Grassland", 2),  # 'disturbance' must not match 'urban'
    ("Edwards Plateau: Ashe Juniper - Live Oak Shrubland", 3),
    ("Native Invasive: Juniper Shrubland", 3),
    ("Edwards Plateau: Shin Oak Shrubland", 4),
    ("Edwards Plateau: Floodplain Deciduous Shrubland", 4),
    ("Row Crops", 5),
    ("Urban Low Intensity", 6),
    ("Open Water", 6),
])
def test_emst_class_rules(name, cls):
    assert emst_class(name) == cls


def test_gap_class_rules():
    assert gap_class("Western Great Plains Mesquite Woodland and Shrubland") == 1
    assert gap_class("Cultivated Cropland") == 5
    assert gap_class("Edwards Plateau Limestone Savanna and Woodland") == 4
    assert gap_class("Developed, Open Space") == 6


def test_block_ids():
    transform = (20.0, 0.0, 500000.0, 0.0, -20.0, 3400000.0)
    b = block_ids((10, 10), transform, 100.0)
    assert len(np.unique(b)) == 4
    assert b[0, 0] == b[4, 4] != b[0, 5]
    assert (b[:5, :5] == b[0, 0]).all()


def test_buffer_zone():
    m = np.zeros((7, 7), bool)
    m[3, 3] = True
    z = buffer_zone(m, 1)
    assert z.sum() == 4 and not z[3, 3]


def test_stratified_sample_caps_per_class():
    strata = np.array([1] * 100 + [2] * 5).reshape(-1, 1)
    idx = stratified_sample(strata, np.ones_like(strata, bool), 10, np.random.default_rng(0))
    vals = strata.ravel()[idx]
    assert (vals == 1).sum() == 10 and (vals == 2).sum() == 5


def test_clustered_sample_makes_patches():
    labels = np.ones((50, 50), dtype=np.uint8)
    idx, seeds = clustered_sample(labels, labels > 0, 50, 5, np.random.default_rng(1))
    assert seeds.shape == idx.shape and (seeds >= 0).all()
    assert len(np.unique(seeds)) < idx.size
    assert 50 <= idx.size <= 50 + 24


# Olofsson et al. (2014), Remote Sensing of Environment 148:42-57, worked example (Tables 8-9):
# strata deforestation, forest gain, stable forest, stable non-forest; 30 m Landsat pixels.
OLOFSSON_N = np.array([[66, 0, 5, 4], [0, 55, 8, 12], [1, 0, 153, 11], [2, 1, 9, 313]])
OLOFSSON_MAPPED_PX = np.array([200_000, 150_000, 3_200_000, 6_450_000])


def test_olofsson_worked_example():
    r = olofsson(OLOFSSON_N, OLOFSSON_MAPPED_PX, pixel_area=0.09)  # hectares
    assert r["estimated_area"][0] == pytest.approx(21_158, abs=5)  # deforestation 21,158 ha
    assert r["estimated_area_ci95"][0] == pytest.approx(6_158, abs=5)  # +/- 6,158 ha
    assert r["estimated_area"][1] == pytest.approx(11_686, abs=5)  # forest gain 11,686 ha
    assert r["estimated_area_ci95"][1] == pytest.approx(3_756, abs=5)  # +/- 3,756 ha
    assert r["overall_accuracy"] == pytest.approx(0.95, abs=0.005)
    assert r["users_accuracy"][0] == pytest.approx(0.88, abs=0.005)
    assert r["producers_accuracy"][0] == pytest.approx(0.75, abs=0.005)
    assert sum(r["estimated_area"]) == pytest.approx(OLOFSSON_MAPPED_PX.sum() * 0.09)


def test_olofsson_guards_small_strata():
    with pytest.warns(UserWarning):
        r = olofsson(np.array([[5, 0], [0, 1]]), [100, 50])
    assert np.isnan(r["overall_accuracy_ci95"]) and r["overall_accuracy"] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        olofsson(np.array([[5, 0], [0, 0]]), [100, 50])


def test_sample_metrics_perfect():
    m = sample_metrics(error_matrix([1, 1, 2, 2], [1, 1, 2, 2], [1, 2]))
    assert m["overall_accuracy"] == 1.0 and m["kappa"] == 1.0


def test_feature_groups_and_configs():
    names = feature_names()
    assert len(names) == 36 + 40 + 36 + 3
    # the cached parts hold every feature exactly once
    stored = [n for p in PARTS if p != "labels" for n in part_names(p)]
    assert sorted(stored) == sorted(names)
    assert "S2_m12_NDVI" in part_names("s2_DJF") and "S2_DJF_B05" in part_names("s2_DJF")
    g = feature_groups(names, by="sensor_season")
    assert set(g) == {f"{s} {p}" for s in ("Sentinel-2", "Sentinel-1")
                      for p in ("winter (Dec-Feb)", "spring (Mar-May)", "summer (Jun-Aug)", "fall (Sep-Nov)")} | {"lidar height"}
    spring = [names[i] for i in g["Sentinel-2 spring (Mar-May)"]]
    assert "S2_m04_NDVI" in spring and "S2_MAM_B05" in spring and "S2_m06_NDVI" not in spring
    m = feature_groups(names, by="month")
    assert len(m) == 12 and len(m["04 Apr"]) == 3 + 3  # three S2 indices + three S1 layers
    assert sum(len(v) for v in g.values()) == len(names)
    assert len(config_columns(names, "S2 only")) == 76
    assert len(config_columns(names, "S1 only")) == 36
    assert len(config_columns(names, "S1 + S2 + lidar")) == 115


def test_s1_orbit_coverage_prefers_full_footprint():
    import datetime as dt
    from types import SimpleNamespace

    from brushmap.data import s1_orbit_coverage

    def item(orbit, day, x0):
        return SimpleNamespace(properties={"sat:relative_orbit": orbit}, datetime=dt.datetime(2020, 1, day),
                               geometry={"type": "Polygon", "coordinates": [[[x0, 0], [2, 0], [2, 1], [x0, 1], [x0, 0]]]})
    items = [item(5, 1, -1), item(5, 13, -1), item(107, 7, 0.4), item(107, 19, 0.4), item(107, 31, 0.4)]
    orbits, cover = s1_orbit_coverage(items, (0, 0, 1, 1))
    assert len(orbits[107]) == 3 and len(orbits[5]) == 2
    assert cover[5] == pytest.approx(1.0) and cover[107] == pytest.approx(0.6)


@pytest.mark.parametrize("name, cls", [
    ("Edwards Plateau: Ashe Juniper Motte and Woodland", 1),
    ("Edwards Plateau: Ashe Juniper - Live Oak Shrubland", 1),  # juniper named first
    ("Edwards Plateau: Riparian Ashe Juniper Shrubland", 1),  # 'Riparian' is a setting, not a plant
    ("Native Invasive: Juniper Shrubland", 1),
    ("Edwards Plateau: Oak / Ashe Juniper Slope Forest", 3),  # oak named first
    ("Native Invasive: Deciduous - Juniper Woodland", 3),
    ("Edwards Plateau: Live Oak Motte and Woodland", 3),
    ("Native Invasive: Mesquite Shrubland", 3),
    ("Edwards Plateau: Savanna Grassland", 2),
    ("Edwards Plateau: Floodplain Herbaceous Vegetation", 2),
    ("Row Crops", 4),
    ("Urban Low Intensity", 4),
])
def test_emst_class_juniper_rules(name, cls):
    assert emst_class_juniper(name) == cls


def test_juniper_first_and_gap_rules():
    assert juniper_first("Edwards Plateau: Ashe Juniper Slope Forest")
    assert not juniper_first("Edwards Plateau: Floodplain Hardwood / Ashe Juniper Forest")
    assert not juniper_first("Edwards Plateau: Live Oak Motte and Woodland")
    assert gap_class_juniper("Cultivated Cropland") == 4
    assert gap_class_juniper("Edwards Plateau Limestone Savanna and Woodland") == 3


def test_set_site_switches_class_table():
    from brushmap import labels

    cfg = set_site("juniper")
    assert labels.CLASSES[cfg["target"]][0] == "Ashe juniper" and len(labels.CLASSES) == 4
    cfg = set_site("mesquite")
    assert labels.CLASSES[cfg["target"]][0] == "Mesquite shrubland" and len(labels.CLASSES) == 6
    for site in SITES.values():
        assert site["target"] in site["classes"] and set(site["woody"]) <= set(site["classes"])


def test_all_modules_import():
    import importlib

    for mod in ("assess", "data", "features", "labels", "plots", "prepare", "train"):
        importlib.import_module(f"brushmap.{mod}")
