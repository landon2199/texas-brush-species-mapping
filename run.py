"""End to end: labels + Sentinel-2 + Sentinel-1 + lidar -> models -> spatial validation -> figures.

Example:
    python run.py                     # Ashe juniper site, Hill Country around Kerrville, Texas, 2020, 10 m
    python run.py --site mesquite     # honey mesquite site, Rolling Plains south of Abilene, Texas
    python run.py --site juniper --bbox -99.20 29.65 -98.94 29.875 --seed 7
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also works with `python -I run.py`

import brushmap  # noqa: F401  (sets MKL/DLL environment before numpy loads)

import argparse
import json
import time

import numpy as np

from brushmap import assess, data, features, labels, plots, prepare, train

ROOT = Path(__file__).resolve().parent
CONFIGS = ["S2 only", "S1 only", "S1 + S2", "S1 + S2 + lidar", "lidar only"]
MAIN = "S1 + S2"  # the published map: satellite only, so it can run where no lidar exists


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", choices=sorted(labels.SITES), default="juniper",
                   help="study site: class rules, default box and output folder (default: juniper)")
    p.add_argument("--bbox", nargs=4, type=float, default=None,
                   metavar=("WEST", "SOUTH", "EAST", "NORTH"), help="WGS 84 bounding box (default: the site's box)")
    p.add_argument("--place", default=None, help="name used in figure titles (default: the site's)")
    p.add_argument("--year", type=int, default=2020, help="image year")
    p.add_argument("--resolution", type=float, default=10.0, help="pixel size in metres")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--block-km", type=float, default=2.0, help="spatial block size for CV and the test split")
    p.add_argument("--test-fraction", type=float, default=0.2, help="share of blocks held out for testing")
    p.add_argument("--buffer-m", type=float, default=200.0, help="training pixels this close to test blocks are dropped")
    p.add_argument("--n-train", type=int, default=2000, help="training pixels per class")
    p.add_argument("--n-test", type=int, default=500, help="test pixels per mapped class (Olofsson sample)")
    p.add_argument("--cluster-px", type=int, default=5, help="patch width (pixels) for the clustered training design")
    p.add_argument("--max-cloud", type=float, default=60.0, help="scene cloud cover limit (%%); clouds are masked per pixel")
    p.add_argument("--s2-per-month", type=int, default=4, help="least-cloudy Sentinel-2 scenes per month")
    p.add_argument("--s1-orbit", type=int, default=None, help="Sentinel-1 relative orbit (default: most frequent ascending)")
    p.add_argument("--cache", type=Path, default=ROOT / "data", help="folder for cached rasters (not in git)")
    args = p.parse_args()
    site = labels.SITES[args.site]
    args.bbox = args.bbox or site["bbox"]
    args.place = args.place or site["place"]
    return args


def tag_of(args):
    return f"{args.site}_{'_'.join(f'{v:.3f}' for v in args.bbox)}_{args.year}_{args.resolution:g}m"


# --------------------------------------------------------------------------- child processes
def _child(target, kwargs, status_file):
    """Run ``target(**kwargs)`` in a spawned process, write a status file, then exit hard.

    On some Windows setups a process that has made GDAL network reads never finishes exiting,
    so the parent waits for the status file and terminates the child instead of joining it.
    """
    import os
    import sys
    import traceback

    import brushmap  # noqa: F401

    code = 0
    try:
        target(**kwargs)
    except Exception:  # noqa: BLE001 - report and signal failure to the parent
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    Path(status_file).write_text(str(code))
    os._exit(code)


def run_children(jobs: dict, cache: Path, timeout_s: float = 900.0, attempts: int = 2):
    """Run several (target, kwargs) jobs in parallel spawned processes; fail if any fails.

    A job that has not finished after ``timeout_s`` seconds is stopped and started again (up to
    ``attempts`` tries): a network read can stall without raising an error, and on the test PC
    one such stall held a Sentinel-2 part for more than 20 minutes.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")

    def start(name):
        target, kwargs = jobs[name]
        sf = cache / f"status_{name}.txt"
        sf.unlink(missing_ok=True)
        p = ctx.Process(target=_child, args=(target, kwargs, str(sf)))
        p.start()
        return p, sf, time.time()

    procs = {name: start(name) for name in jobs}
    tries = {name: 1 for name in jobs}
    failed = []
    while procs:
        time.sleep(1)
        for name, (p, sf, t_start) in list(procs.items()):
            if not sf.exists() and p.is_alive():
                if time.time() - t_start > timeout_s:
                    p.terminate()
                    del procs[name]
                    if tries[name] < attempts:
                        print(f"{name}: no result after {timeout_s:.0f} s, restarting", flush=True)
                        tries[name] += 1
                        procs[name] = start(name)
                    else:
                        failed.append(name)
                continue
            time.sleep(0.5)
            status = int(sf.read_text() or 1) if sf.exists() else (p.exitcode or 1)
            if p.is_alive():
                p.terminate()
            sf.unlink(missing_ok=True)
            del procs[name]
            if status != 0:
                failed.append(name)
    if failed:
        raise SystemExit(f"Data step(s) failed: {failed}; see the traceback above.")


def fetch_naip_chips(points, epsg, year, half_m, out_file):
    """Child-process job: NAIP windows around map points, saved to one .npz file."""
    data.configure_gdal()
    chips, extents, ids = [], [], []
    for x, y in points:
        arr, ext, iid = data.load_naip(x, y, half_m, epsg, year)
        chips.append(arr[:3] if arr is not None else np.zeros((3, 2, 2), "uint8"))
        extents.append(ext or (x - half_m, x + half_m, y - half_m, y + half_m))
        ids.append(iid or "")
    np.savez_compressed(out_file, chips=np.array(chips, dtype=object), extents=np.array(extents),
                        ids=np.array(ids))


def peak_memory_gb():
    try:
        import psutil

        info = psutil.Process().memory_info()
        return round(getattr(info, "peak_wset", info.rss) / 1e9, 2)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- main
def main():
    args = parse_args()
    data.configure_gdal()
    from threadpoolctl import threadpool_limits

    # OpenMP (used by gradient boosting) ran up to 7x slower with all 24 threads than with 8 on the
    # test PC (thread oversubscription), so it is capped here. Random Forest uses joblib threads.
    threadpool_limits(8, user_api="openmp")
    t0 = time.time()
    tag = tag_of(args)
    site = labels.set_site(args.site)
    T, G = site["target"], site["grass"]  # class codes of the target species and of grassland
    args.cache.mkdir(parents=True, exist_ok=True)
    figs, res_dir = ROOT / "figures" / args.site, ROOT / "results" / args.site
    figs.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    todo = [p for p in prepare.PARTS if not all(x.exists() for x in prepare.part_paths(args.cache, tag, p))]
    if todo:
        print(f"Building inputs in parallel processes: {todo}")
        kw = dict(site=args.site, bbox=args.bbox, year=args.year, resolution=args.resolution, cache=args.cache, tag=tag,
                  max_cloud=args.max_cloud, s2_per_month=args.s2_per_month, s1_orbit=args.s1_orbit)
        run_children({p: (prepare.build_part, {"part": p, **kw}) for p in todo}, args.cache)
    stack, names, lab, lab_names, grid, meta = prepare.load_inputs(args.cache, tag)
    t_data = time.time() - t0
    print(f"Inputs ready: {len(names)} features on a {grid.shape[0]} x {grid.shape[1]} grid ({t_data:.0f} s)")

    emst = lab[lab_names.index("emst_class")].astype("uint8")
    gap = lab[lab_names.index("gap_class")].astype("uint8")
    finite = np.isfinite(stack).all(axis=0)
    valid = finite & (emst > 0)
    classes = sorted(int(c) for c in np.unique(emst[valid]) if c > 0)
    cname = {c: labels.CLASSES[c][0] for c in classes}
    shares = {cname[c]: round(float((emst[valid] == c).mean()), 4) for c in classes}
    print("Class shares (EMST):", shares)

    # ---- spatial split: whole blocks held out for testing, a buffer removed around them
    blocks = train.block_ids(grid.shape, grid.transform, args.block_km * 1000)
    test_mask = train.split_test_blocks(blocks, valid, args.test_fraction, args.seed)
    buffer = train.buffer_zone(test_mask, int(round(args.buffer_m / args.resolution)))
    train_area = valid & ~test_mask & ~buffer
    test_pop = valid & test_mask
    test_flat = np.flatnonzero(test_pop.ravel())

    X_all = stack.reshape(stack.shape[0], -1).T  # pixels x features (a view, no copy)
    y_all = emst.ravel()
    rng = np.random.default_rng(args.seed)
    tr_idx = train.stratified_sample(emst, train_area, args.n_train, rng)
    X_tr, y_tr = X_all[tr_idx], y_all[tr_idx]
    groups = blocks.ravel()[tr_idx]
    xy_tr = train.pixel_coords(tr_idx, grid.shape, grid.transform)
    print(f"Training sample: {tr_idx.size} pixels from {np.unique(groups).size} blocks; "
          f"test population {test_pop.sum()} pixels in {np.unique(blocks[test_mask]).size} blocks")

    cols = {c: features.config_columns(names, c) for c in CONFIGS}
    models = train.make_models(args.seed)
    from sklearn.base import clone
    from sklearn.metrics import balanced_accuracy_score

    cv, fitted, timing = {}, {}, {}
    for config in CONFIGS:
        Xc = X_tr[:, cols[config]]
        for mname, model in models.items():
            key = f"{mname}|{config}"
            t1 = time.time()
            fitted[key] = clone(model).fit(Xc, y_tr)
            cv[key] = {}
            # Gradient boosting is about 5x slower to fit, so its CV is run for the main configuration only.
            if mname == "random_forest" or config == MAIN:
                cv[key]["random_cv"] = train.cross_validate(model, Xc, y_tr, None, seed=args.seed)
                cv[key]["spatial_cv"] = train.cross_validate(model, Xc, y_tr, groups, seed=args.seed, coords=xy_tr)
                print(f"{key}: random CV BA {cv[key]['random_cv']['balanced_accuracy']:.3f} | spatial CV BA "
                      f"{cv[key]['spatial_cv']['balanced_accuracy']:.3f}", flush=True)
            timing[key] = round(time.time() - t1, 1)

    # Clustered (polygon-like) training design for the main RF configuration: shows how much the
    # sampling design inflates random CV.
    cl_idx, cl_seed = train.clustered_sample(emst, train_area, args.n_train, args.cluster_px,
                                             np.random.default_rng(args.seed))
    Xcl = X_all[cl_idx][:, cols[MAIN]]
    ycl = y_all[cl_idx]
    gcl = blocks.ravel()[cl_seed]
    rf_cl = clone(models["random_forest"]).fit(Xcl, ycl)
    cv_clustered = {
        "random_cv": train.cross_validate(models["random_forest"], Xcl, ycl, None, seed=args.seed),
        "spatial_cv": train.cross_validate(models["random_forest"], Xcl, ycl, gcl, seed=args.seed),
        "test": assess.sample_metrics(assess.error_matrix(
            train.predict_pixels(rf_cl, X_all, test_flat, cols[MAIN]), y_all[test_flat], classes)),
        "n_pixels": int(cl_idx.size), "n_patches": int(np.unique(cl_seed).size),
    }
    print(f"RF {MAIN} clustered: random CV {cv_clustered['random_cv']['balanced_accuracy']:.3f}, spatial "
          f"{cv_clustered['spatial_cv']['balanced_accuracy']:.3f}, test {cv_clustered['test']['balanced_accuracy']:.3f}")

    # ---- held-out blocks: census + Olofsson et al. (2014) stratified sample for every model
    px_km2 = (args.resolution / 1000) ** 2
    ref_test = y_all[test_flat]
    results, test_pred = {}, {}
    for key, model in fitted.items():
        mname, config = key.split("|")
        t1 = time.time()
        pred = train.predict_pixels(model, X_all, test_flat, cols[config])
        test_pred[key] = pred
        census = assess.sample_metrics(assess.error_matrix(pred, ref_test, classes))
        test_map = np.zeros(emst.size, dtype="uint8")
        test_map[test_flat] = pred
        s_idx = train.stratified_sample(test_map.reshape(emst.shape), test_pop, args.n_test,
                                        np.random.default_rng(args.seed + 1))
        n = assess.error_matrix(test_map[s_idx], y_all[s_idx], classes)
        map_counts = [int((pred == c).sum()) for c in classes]
        olof = assess.olofsson(n, map_counts, pixel_area=px_km2)
        olof["emst_area_census"] = [int((ref_test == c).sum()) * px_km2 for c in classes]
        olof["ci_covers_census"] = [bool(abs(e - c) <= h) for e, c, h in
                                    zip(olof["estimated_area"], olof["emst_area_census"], olof["estimated_area_ci95"])]
        results[key] = {"census": census, "olofsson": olof, "counts": n.tolist(), "sample_index": s_idx}
        cv[key]["test"] = census
        print(f"{key}: held-out census BA {census['balanced_accuracy']:.3f} | Olofsson OA "
              f"{olof['overall_accuracy']:.3f} +/- {olof['overall_accuracy_ci95']:.3f} ({time.time() - t1:.0f} s)")

    main_key = f"random_forest|{MAIN}"
    lidar_key = "random_forest|S1 + S2 + lidar"

    # ---- grouped permutation importance (held-out Olofsson sample)
    s_main = results[main_key]["sample_index"]
    pi = {}
    for key, by in ((lidar_key, "sensor_season"), (main_key, "month")):
        cfg = key.split("|")[1]
        sub = [names[i] for i in cols[cfg]]
        groups_fi = assess.feature_groups(sub, by=by)
        Xs = X_all[results[key]["sample_index"]][:, cols[cfg]]
        ys = y_all[results[key]["sample_index"]]
        base, imp = assess.grouped_permutation_importance(fitted[key], Xs, ys, groups_fi, balanced_accuracy_score,
                                                          n_repeats=10, seed=args.seed)
        pi[by] = {"model": key, "baseline_balanced_accuracy": base,
                  "groups": {g: {"mean_drop": m, "sd": s, "features": [sub[i] for i in groups_fi[g]]}
                             for g, (m, s) in imp.items()}}
    print("Permutation importance done")

    # ---- full map with the main model
    pred_map = train.predict_raster(fitted[main_key], X_all, valid, cols[MAIN])
    data.save_stack(args.cache / f"rf_map_{tag}.tif", pred_map, ["rf_class_s1_s2"], grid, nodata=0)

    # ---- phenology curves per EMST class (random sample of valid pixels per class)
    crng = np.random.default_rng(args.seed + 2)
    frac = stack[names.index("LIDAR_frac1m")]
    curves = {}
    per_class = {c: crng.choice(np.flatnonzero((valid & (emst == c)).ravel()),
                                size=min(20000, int((valid & (emst == c)).sum())), replace=False) for c in classes}
    # "Core" pixels: the target class where lidar sees >= 30 % woody cover, grassland where it sees < 5 %.
    core = {f"{cname[T]}, lidar woody cover >= 30 %": valid & (emst == T) & (frac >= 0.3),
            f"{cname[G]}, lidar woody cover < 5 %": valid & (emst == G) & (frac < 0.05)}
    core_idx = {k: crng.choice(np.flatnonzero(m.ravel()), size=min(20000, int(m.sum())), replace=False)
                for k, m in core.items()}
    for var in ("NDVI", "NDRE", "NDMI"):
        rows = [names.index(f"S2_m{m:02d}_{var}") for m in features.MONTHS]
        curves[var] = {cname[c]: np.percentile(X_all[idx][:, rows], [25, 50, 75], axis=0).tolist()
                       for c, idx in per_class.items()}
        curves[var].update({k: np.percentile(X_all[idx][:, rows], [25, 50, 75], axis=0).tolist()
                            for k, idx in core_idx.items()})
    for var in ("VV", "VH", "VHVV"):
        rows = [names.index(f"S1_m{m:02d}_{var}") for m in features.MONTHS]
        curves[var] = {cname[c]: np.percentile(X_all[idx][:, rows], [25, 50, 75], axis=0).tolist()
                       for c, idx in per_class.items()}
        curves[var].update({k: np.percentile(X_all[idx][:, rows], [25, 50, 75], axis=0).tolist()
                            for k, idx in core_idx.items()})

    # ---- lidar woody cover by class (EMST label and mapped class, test blocks)
    lidar_check = {"by_emst_class": {}, "by_mapped_class_test_blocks": {}}
    for c in classes:
        f_ref = frac[valid & (emst == c)]
        f_map = frac.ravel()[test_flat][test_pred[main_key] == c]
        for dest, f in (("by_emst_class", f_ref), ("by_mapped_class_test_blocks", f_map)):
            if f.size == 0:
                continue
            lidar_check[dest][cname[c]] = {
                "n_pixels": int(f.size),
                "woody_cover_quartiles": np.percentile(f, [25, 50, 75]).round(3).tolist(),
                "share_below_10pct": round(float((f < 0.10).mean()), 3),
                "share_above_25pct": round(float((f > 0.25).mean()), 3),
            }
    s_pred = np.zeros(emst.size, "uint8")
    s_pred[test_flat] = test_pred[main_key]
    # "Core" test pixels where the EMST label and the independent lidar agree on structure:
    # how does the satellite-only map do where the label is most likely right?
    f_test = frac.ravel()[test_flat]
    core_defs = {
        f"EMST {cname[T]}, lidar woody cover >= 25 %": ((ref_test == T) & (f_test >= 0.25), T),
        f"EMST {cname[T]}, lidar woody cover < 10 %": ((ref_test == T) & (f_test < 0.10), T),
        f"EMST {cname[G]}, lidar woody cover < 5 %": ((ref_test == G) & (f_test < 0.05), G),
        f"EMST {cname[G]}, lidar woody cover >= 25 %": ((ref_test == G) & (f_test >= 0.25), G),
    }
    woody_classes = [c for c in site["woody"] if c in classes]
    core_check = {}
    for nm, (m, ref_c) in core_defs.items():
        p = test_pred[main_key][m]
        if p.size == 0:
            continue
        core_check[nm] = {"n_pixels": int(p.size),
                          "share_of_test_class": round(float(m.sum() / max((ref_test == ref_c).sum(), 1)), 3),
                          "mapped_as": {cname[c]: round(float((p == c).mean()), 3) for c in classes},
                          "mapped_as_any_woody_class": round(float(np.isin(p, woody_classes).mean()), 3)}
    # Woody vs non-woody, judged by lidar alone (>= 25 % of 2 m cells taller than 1 m = woody)
    lidar_woody = f_test >= 0.25
    map_woody = np.isin(test_pred[main_key], woody_classes)
    emst_woody = np.isin(ref_test, woody_classes)
    woody_check = {
        "threshold": "lidar woody cover >= 25 % of 2 m cells taller than 1 m",
        "map_agrees_with_lidar": round(float((map_woody == lidar_woody).mean()), 3),
        "emst_agrees_with_lidar": round(float((emst_woody == lidar_woody).mean()), 3),
        "share_test_pixels_lidar_woody": round(float(lidar_woody.mean()), 3),
        "share_test_pixels_map_woody": round(float(map_woody.mean()), 3),
        "share_test_pixels_emst_woody": round(float(emst_woody.mean()), 3),
    }
    print("Core check:", json.dumps(core_check)[:600], "| woody vs lidar:", woody_check, flush=True)
    # How each EMST type inside the test blocks is mapped (the classes merge several types, some
    # of them mixtures such as "Ashe Juniper - Live Oak Shrubland").
    veg_test = lab[lab_names.index("emst_veg_id")].ravel()[test_flat]
    type_names = {int(k): v["name"] for k, v in meta["labels"]["emst"]["types"].items()}
    by_type = {}
    for vid in sorted(np.unique(veg_test), key=lambda v: -(veg_test == v).sum())[:15]:
        m = veg_test == vid
        if m.sum() < 2000:
            continue
        p = test_pred[main_key][m]
        by_type[type_names.get(int(vid), str(vid))] = {
            "label_class": cname.get(int(np.bincount(ref_test[m]).argmax()), "excluded"),
            "n_test_pixels": int(m.sum()),
            "mapped_as": {cname[c]: round(float((p == c).mean()), 3) for c in classes}}

    # ---- EMST vs GAP agreement (both are maps; neither is ground truth)
    both = valid & (gap > 0)
    gap_vs_emst = {cname[c]: {cname[g] if g in cname else str(g): round(float(((gap == g) & both & (emst == c)).sum()
                                                                              / max(((emst == c) & both).sum(), 1)), 3)
                              for g in classes} for c in classes}
    mesq_e, mesq_g = (emst == T) & both, (gap == T) & both  # target class in each map
    gap_summary = {
        "share_of_emst_target_also_gap_target": round(float((mesq_e & mesq_g).sum() / max(mesq_e.sum(), 1)), 3),
        "share_of_gap_target_also_emst_target": round(float((mesq_e & mesq_g).sum() / max(mesq_g.sum(), 1)), 3),
        "overall_class_agreement": round(float((emst[both] == gap[both]).mean()), 3),
        "gap_target_share_of_area": round(float(mesq_g.sum() / max(both.sum(), 1)), 4),
        "emst_target_share_of_area": round(float(mesq_e.sum() / max(both.sum(), 1)), 4),
        "rows_emst_cols_gap": gap_vs_emst,
    }

    # ---- NAIP: one inset window and spot-check chips (fetched in a child process)
    epsg = int(grid.crs.split(":")[1])
    s_idx = results[main_key]["sample_index"]
    s_map = s_pred[s_idx]
    srng = np.random.default_rng(args.seed + 3)
    c1, c2, c3 = site["checks"]  # 12 pixels of the target class, 6 each of two other classes
    chk_m = srng.choice(s_idx[s_map == c1], size=min(12, int((s_map == c1).sum())), replace=False)
    chk_g = srng.choice(s_idx[s_map == c2], size=min(6, int((s_map == c2).sum())), replace=False)
    chk_j = srng.choice(s_idx[s_map == c3], size=min(6, int((s_map == c3).sum())), replace=False)
    chk = np.concatenate([chk_m, chk_g, chk_j])
    chk_xy = train.pixel_coords(chk, grid.shape, grid.transform)
    # Inset: the 300 m window (in the test blocks) with the widest spread of lidar woody cover
    # among pixels of the target class.
    win = 30
    best, best_score = None, -1
    for b in np.unique(blocks[test_mask])[:60]:
        rr, cc = np.nonzero(blocks == b)
        r0, c0 = rr.min() + 35, cc.min() + 35
        w_e, w_f = emst[r0:r0 + win, c0:c0 + win], frac[r0:r0 + win, c0:c0 + win]
        if w_e.shape != (win, win) or not np.isfinite(w_f).all():
            continue
        score = (w_e == T).mean() * np.std(w_f)
        if score > best_score:
            best, best_score = (r0, c0), score
    r0, c0 = best
    inset_xy = train.pixel_coords(np.array([(r0 + win // 2) * grid.shape[1] + c0 + win // 2]), grid.shape,
                                  grid.transform)
    naip_file = args.cache / f"naip_{tag}_{args.seed}.npz"
    pts = [tuple(p) for p in np.vstack([inset_xy, chk_xy])]
    if not naip_file.exists():
        naip_year = 2020 if args.year in (2019, 2020, 2021) else args.year
        run_children({"naip": (fetch_naip_chips, dict(points=pts, epsg=epsg, year=naip_year, half_m=150.0,
                                                       out_file=str(naip_file)))}, args.cache)
    nz = np.load(naip_file, allow_pickle=True)
    naip_chips, naip_ext, naip_ids = list(nz["chips"]), nz["extents"], list(nz["ids"])

    # ---- figures
    res = args.resolution / 1000
    extent = [0, grid.shape[1] * res, 0, grid.shape[0] * res]
    ref_show = np.where(valid, emst, 0)
    pred_show = np.where(valid, pred_map, 0)
    main_res = results[main_key]
    plots.hero_figure(pred_show, ref_show, classes, extent, curves["NDVI"], main_res["olofsson"], cv, MAIN,
                      figs / "hero.png", args.place, args.year, site)
    plots.class_curves(curves, classes, figs / "class_curves.png", args.year)
    plots.model_comparison(cv, CONFIGS, figs / "model_comparison.png", cv_clustered, args.cluster_px, MAIN)
    plots.confusion_figure(main_res["counts"], classes, main_res["olofsson"]["users_accuracy"],
                           main_res["olofsson"]["producers_accuracy"], figs / "confusion_matrix.png",
                           f"Random Forest ({MAIN}), held-out sample (n = {int(np.sum(main_res['counts']))}); "
                           "UA/PA area-weighted")
    plots.importance_figure(pi, figs / "feature_importance.png")
    win_sl = (slice(r0, r0 + win), slice(c0, c0 + win))
    plots.naip_inset(naip_chips[0], naip_ext[0], emst[win_sl], pred_map[win_sl], frac[win_sl],
                     stack[names.index("LIDAR_max")][win_sl], classes, figs / "naip_inset.png", naip_ids[0])
    short = {c: cname[c].split(" (")[0].split(" /")[0] for c in classes}
    chk_labels = [f"map {short[int(s_pred[i])]} | EMST {short[int(y_all[i])]}"
                  f" | lidar {100 * frac.ravel()[i]:.0f}%" for i in chk]
    plots.naip_chips(naip_chips[1:], naip_ext[1:], chk_xy, chk_labels, figs / "naip_spot_checks.png",
                     args.resolution)
    plots.lidar_check_figure(frac, emst, valid, test_flat, test_pred[main_key], classes, figs / "lidar_check.png")

    # ---- metrics.json
    def r(x, k=4):
        if isinstance(x, list):
            return [r(v, k) for v in x]
        if isinstance(x, dict):
            return {kk: r(vv, k) for kk, vv in x.items()}
        return round(float(x), k) if isinstance(x, (float, np.floating)) else x

    class_names = [cname[c] for c in classes]
    out = {
        "run": {"site": args.site, "species": site["species"], "bbox_wgs84": args.bbox, "place": args.place, "year": args.year, "resolution_m": args.resolution,
                "seed": args.seed, "crs": grid.crs, "grid_shape": list(grid.shape), "block_km": args.block_km,
                "test_fraction_of_blocks": args.test_fraction, "buffer_m": args.buffer_m,
                "n_train_per_class": args.n_train, "n_test_per_class": args.n_test,
                "runtime_seconds": round(time.time() - t0, 1), "data_seconds": round(t_data, 1),
                "peak_memory_gb_main_process": peak_memory_gb(),
                "prepare_seconds_per_parallel_part": {p: meta[p]["seconds"] for p in prepare.PARTS}},
        "inputs": {
            "sentinel2_months": {m: v for p in prepare.PARTS if p.startswith("s2_") for m, v in meta[p]["months"].items()},
            "sentinel1": {"orbit_state": meta["s1_MAM"]["orbit_state"], "relative_orbit": meta["s1_MAM"]["relative_orbit"],
                          "dates_per_orbit": meta["s1_MAM"]["dates_per_orbit"],
                          "months": {m: v for p in prepare.PARTS if p.startswith("s1_") for m, v in meta[p]["months"].items()}},
            "lidar": {k: v for k, v in meta["lidar"].items() if k not in ("crs", "grid_shape")},
            "gap_filling": meta["gap_filling"],
            "share_of_labelled_pixels_with_all_features": round(float(valid.sum() / max((emst > 0).sum(), 1)), 4),
            "share_of_grid_with_emst_label": round(float((emst > 0).mean()), 4),
        },
        "labels": {"source": "TPWD Ecological Mapping Systems of Texas (map service 2020)",
                   "classes": classes, "class_names": class_names, "class_shares": shares,
                   "emst_types": meta["labels"]["emst"], "gap_types": meta["labels"]["gap"]},
        "samples": {"train": int(tr_idx.size), "train_blocks": int(np.unique(groups).size),
                    "test_blocks": int(np.unique(blocks[test_mask]).size), "test_population_pixels": int(test_pop.sum())},
        "cross_validation": {k: {s: {kk: r(vv) for kk, vv in d.items() if not isinstance(vv, list)}
                                 for s, d in v.items()} for k, v in cv.items()},
        "clustered_design_rf_main": {k: (r({kk: vv for kk, vv in v.items() if not isinstance(vv, list)})
                                         if isinstance(v, dict) else v) for k, v in cv_clustered.items()},
        "fit_seconds": timing,
        "test": {},
        "grouped_permutation_importance": r(pi),
        "phenology_medians": {var: {cls: r(v[1], 3) for cls, v in d.items()} for var, d in curves.items()},
        "lidar_check": lidar_check,
        "core_pixel_check_main_model": core_check,
        "woody_vs_lidar_check": woody_check,
        "emst_type_breakdown_test_blocks": by_type,
        "emst_vs_gap": gap_summary,
        "naip_items": sorted(set(naip_ids)),
    }
    for key, d in results.items():
        o, c = d["olofsson"], d["census"]
        out["test"][key] = {
            "census_of_test_blocks": {
                "overall_accuracy": r(c["overall_accuracy"]), "balanced_accuracy": r(c["balanced_accuracy"]),
                "macro_f1": r(c["macro_f1"]), "kappa": r(c["kappa"]),
                "per_class": {nm: {"users_accuracy": r(u), "producers_accuracy": r(p)}
                              for nm, u, p in zip(class_names, c["users_accuracy"], c["producers_accuracy"])}},
            "olofsson_2014": {
                "sample_size": int(np.sum(d["counts"])), "sample_counts_rows_map_cols_reference": d["counts"],
                "overall_accuracy": r(o["overall_accuracy"]), "overall_accuracy_ci95": r(o["overall_accuracy_ci95"]),
                "per_class": {nm: {
                    "users_accuracy": r(o["users_accuracy"][k]), "users_accuracy_ci95": r(o["users_accuracy_ci95"][k]),
                    "producers_accuracy": r(o["producers_accuracy"][k]),
                    "producers_accuracy_ci95": r(o["producers_accuracy_ci95"][k]),
                    "mapped_area_km2": r(o["mapped_area"][k], 2), "estimated_area_km2": r(o["estimated_area"][k], 2),
                    "estimated_area_ci95_km2": r(o["estimated_area_ci95"][k], 2),
                    "emst_census_area_km2": r(o["emst_area_census"][k], 2), "ci_covers_census": o["ci_covers_census"][k],
                } for k, nm in enumerate(class_names)}},
        }
    out["run"]["runtime_seconds"] = round(time.time() - t0, 1)
    out["run"]["peak_memory_gb_main_process"] = peak_memory_gb()
    (res_dir / "metrics.json").write_text(json.dumps(out, indent=1))
    print(f"Done in {time.time() - t0:.0f} s (peak memory {peak_memory_gb()} GB). "
          f"Metrics: results/{args.site}/metrics.json, figures: figures/{args.site}/")


if __name__ == "__main__":
    main()
