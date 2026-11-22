"""Spatial blocks, sampling designs, models and cross-validation (adapted from sentinel2-landcover-ml)."""
from __future__ import annotations

import numpy as np
from scipy import ndimage
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, KFold

def block_ids(shape, transform, block_size_m: float) -> np.ndarray:
    """Integer id of the square ``block_size_m`` block containing each pixel centre.

    Blocks are aligned to the grid origin, so ids are reproducible for a given grid.
    """
    a, _, c, _, e, f = transform[:6]
    rows, cols = shape
    x = c + (np.arange(cols) + 0.5) * a
    y = f + (np.arange(rows) + 0.5) * e
    bx = np.floor((x - c) / block_size_m).astype(int)
    by = np.floor((f - y) / block_size_m).astype(int)
    nbx = bx.max() + 1
    return by[:, None] * nbx + bx[None, :]


def split_test_blocks(blocks: np.ndarray, usable: np.ndarray, test_fraction: float, seed: int) -> np.ndarray:
    """Randomly hold out ``test_fraction`` of the blocks that contain usable pixels."""
    rng = np.random.default_rng(seed)
    ids = np.unique(blocks[usable])
    n_test = max(1, int(round(test_fraction * ids.size)))
    test_ids = rng.choice(ids, size=n_test, replace=False)
    return np.isin(blocks, test_ids)


def buffer_zone(mask: np.ndarray, distance_px: int) -> np.ndarray:
    """Pixels outside ``mask`` but within ``distance_px`` of it."""
    if distance_px <= 0:
        return np.zeros_like(mask, dtype=bool)
    dist = ndimage.distance_transform_edt(~mask)
    return (dist > 0) & (dist <= distance_px)


def stratified_sample(strata: np.ndarray, eligible: np.ndarray, n_per_class: int, rng) -> np.ndarray:
    """Flat pixel indices: up to ``n_per_class`` random pixels from each stratum (> 0)."""
    flat_strata = strata.ravel()
    flat_ok = eligible.ravel()
    picks = []
    for code in np.unique(flat_strata[flat_ok]):
        if code == 0:
            continue
        idx = np.flatnonzero(flat_ok & (flat_strata == code))
        take = min(n_per_class, idx.size)
        picks.append(rng.choice(idx, size=take, replace=False))
    return np.sort(np.concatenate(picks))


def clustered_sample(labels: np.ndarray, eligible: np.ndarray, n_per_class: int, cluster_px: int, rng):
    """Polygon-like training data: whole ``cluster_px`` x ``cluster_px`` patches of one class.

    Mimics hand-digitized training polygons: random seed pixels are expanded to the
    surrounding window, keeping eligible pixels of the seed's class, until ``n_per_class``
    pixels are collected. Neighbouring pixels are near-duplicates, which is exactly what
    makes random cross-validation optimistic.

    Returns (flat pixel indices, flat index of each pixel's patch seed). Grouping CV folds by
    the seed's block keeps a whole patch in one fold even when it straddles a block edge.
    """
    rows, cols = labels.shape
    h = cluster_px // 2
    picks, seeds_all = [], []
    for code in np.unique(labels[eligible]):
        if code == 0:
            continue
        ok = eligible & (labels == code)
        seeds = rng.permutation(np.flatnonzero(ok.ravel()))
        taken = np.zeros(ok.shape, dtype=bool)
        seed_of = np.full(ok.shape, -1, dtype=np.int64)
        count = 0
        for s in seeds:
            if count >= n_per_class:
                break
            r, c = divmod(int(s), cols)
            if taken[r, c]:
                continue
            r0, r1, c0, c1 = max(r - h, 0), min(r + h + 1, rows), max(c - h, 0), min(c + h + 1, cols)
            win = ok[r0:r1, c0:c1] & ~taken[r0:r1, c0:c1]
            taken[r0:r1, c0:c1] |= win
            seed_of[r0:r1, c0:c1][win] = s
            count += int(win.sum())
        picks.append(np.flatnonzero(taken.ravel()))
        seeds_all.append(seed_of.ravel()[picks[-1]])
    idx = np.concatenate(picks)
    seeds = np.concatenate(seeds_all)
    order = np.argsort(idx)
    return idx[order], seeds[order]


def make_models(seed: int) -> dict:
    """Random Forest (main model) and a histogram gradient-boosting baseline."""
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=300, max_features="sqrt", min_samples_leaf=1, n_jobs=-1, random_state=seed
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.15, early_stopping=False, random_state=seed
        ),
    }


def cross_validate(model, X, y, groups=None, n_splits: int = 5, seed: int = 0, coords=None,
                   buffer_m: float = 0.0) -> dict:
    """K-fold CV; random folds when ``groups`` is None, otherwise grouped (spatial) folds.

    With ``coords`` (n x 2, metres) and ``buffer_m`` > 0, training samples closer than
    ``buffer_m`` to any sample of the held-out fold are dropped from that fold's training set.
    """
    from sklearn.base import clone

    if groups is None:
        splits = KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(X)
    else:
        splits = GroupKFold(n_splits=n_splits).split(X, y, groups)
    oa, ba, f1 = [], [], []
    for tr, te in splits:
        if buffer_m > 0 and coords is not None:
            from scipy.spatial import cKDTree

            dist, _ = cKDTree(coords[te]).query(coords[tr], k=1, distance_upper_bound=buffer_m)
            tr = tr[~np.isfinite(dist)]
        m = clone(model).fit(X[tr], y[tr])
        p = m.predict(X[te])
        oa.append(accuracy_score(y[te], p))
        ba.append(balanced_accuracy_score(y[te], p))
        f1.append(f1_score(y[te], p, average="macro"))
    return {
        "overall_accuracy": float(np.mean(oa)),
        "overall_accuracy_sd": float(np.std(oa)),
        "balanced_accuracy": float(np.mean(ba)),
        "balanced_accuracy_sd": float(np.std(ba)),
        "macro_f1": float(np.mean(f1)),
    }


def pixel_coords(flat_idx: np.ndarray, shape, transform) -> np.ndarray:
    """Map coordinates (x, y in CRS units) of pixel centres given flat indices."""
    a, _, c, _, e, f = transform[:6]
    r, col = np.divmod(np.asarray(flat_idx), shape[1])
    return np.column_stack([c + (col + 0.5) * a, f + (r + 0.5) * e])


def predict_pixels(model, X_all: np.ndarray, flat_idx: np.ndarray, columns=None, chunk: int = 200_000) -> np.ndarray:
    """Predict the pixels ``flat_idx`` of a (pixels x features) matrix, optionally on a column subset."""
    out = np.zeros(flat_idx.size, dtype="uint8")
    for s in range(0, flat_idx.size, chunk):
        Xs = X_all[flat_idx[s : s + chunk]]
        out[s : s + chunk] = model.predict(Xs if columns is None else Xs[:, columns])
    return out


def predict_raster(model, X_all: np.ndarray, valid: np.ndarray, columns=None, chunk: int = 200_000) -> np.ndarray:
    """Classify every valid pixel (0 = no prediction)."""
    idx = np.flatnonzero(valid.ravel())
    out = np.zeros(valid.size, dtype="uint8")
    out[idx] = predict_pixels(model, X_all, idx, columns, chunk)
    return out.reshape(valid.shape)
