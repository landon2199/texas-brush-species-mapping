"""Figures."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from .features import MONTH_ABBR  # noqa: E402
from .labels import CLASSES  # noqa: E402

INK = "#1f2328"
MUTED = "#57606a"
GRID = "#d0d7de"
SCHEME = {"random_cv": ("Random 5-fold CV", "#b4b4b4", "o"),
          "spatial_cv": ("Spatial 2 km block CV", "#2f5d8a", "s"),
          "test": ("Held-out test blocks", "#16324f", "D")}
CORE_COLOR = {"Grassland": "#b8a800"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK,
    "axes.titlecolor": INK, "axes.titleweight": "bold", "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white", "savefig.facecolor": "white",
})


def class_cmap(classes):
    codes = [0] + list(classes)
    colors = ["#ffffff"] + [CLASSES[c][1] for c in classes]
    return ListedColormap(colors), BoundaryNorm(np.arange(len(codes) + 1) - 0.5, len(codes)), {c: k for k, c in enumerate(codes)}


def _index_image(img, lut):
    out = np.zeros(img.shape, dtype=np.int16)
    for c, k in lut.items():
        out[img == c] = k
    return out


def _legend_handles(classes):
    return [Patch(facecolor=CLASSES[c][1], edgecolor="#888888", label=CLASSES[c][0]) for c in classes]


def _draw_map(ax, img, classes, title, extent_km, fontsize=13):
    cmap, norm, lut = class_cmap(classes)
    ax.imshow(_index_image(img, lut), cmap=cmap, norm=norm, interpolation="nearest", extent=extent_km)
    ax.set_title(title, loc="left", fontsize=fontsize)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(True)
        s.set_color(GRID)


def _curve(ax, q, color, label, dashed=False, band=True):
    x = np.arange(1, 13)
    q = np.asarray(q)
    if band and not dashed:
        ax.fill_between(x, q[0], q[2], color=color, alpha=0.15, linewidth=0)
    ax.plot(x, q[1], color=color, linewidth=2.4 if not dashed else 2.0, linestyle="--" if dashed else "-",
            marker="o", markersize=4, label=label)


def _month_axis(ax):
    ax.set_xticks(range(1, 13), [m[0] for m in MONTH_ABBR])
    ax.set_xlim(0.6, 12.4)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def hero_figure(pred, ref, classes, extent_km, ndvi, olof, cv, main, path, place, year, site):
    fig = plt.figure(figsize=(16, 7.4), dpi=100)
    gs = fig.add_gridspec(2, 3, width_ratios=[1, 1, 1.05], height_ratios=[0.16, 1], left=0.03, right=0.98,
                          top=0.96, bottom=0.12, wspace=0.16, hspace=0.2)
    head = fig.add_subplot(gs[0, :])
    head.axis("off")
    head.text(0, 0.75, f"Mapping {site['species'].split(' (')[0]} with Sentinel-1 and Sentinel-2", fontsize=20,
              weight="bold", color=INK, va="center")
    head.text(0, 0.05, f"{place}  |  {year}  |  10 m pixels  |  labels: TPWD EMST map",
              fontsize=13.5, color=MUTED, va="center")
    _draw_map(fig.add_subplot(gs[1, 0]), pred, classes, f"Random Forest map ({main})", extent_km, 15)
    _draw_map(fig.add_subplot(gs[1, 1]), ref, classes, "TPWD EMST reference labels", extent_km, 15)
    ax = fig.add_subplot(gs[1, 2])
    for c in classes:
        name = CLASSES[c][0]
        if name in ndvi and c in site["curves"]:
            _curve(ax, ndvi[name], CLASSES[c][1], name, band=(c == site["target"]))
    _month_axis(ax)
    ax.set_ylabel("Median NDVI (shading: middle 50 % of target pixels)")
    ax.set_title("Greenness through the year", loc="left", fontsize=15)
    k = classes.index(site["target"])
    tname = CLASSES[site["target"]][0]
    head.text(1.0, 0.75, f"{tname}: user's {olof['users_accuracy'][k]:.2f}, producer's {olof['producers_accuracy'][k]:.2f}",
              fontsize=14.5, weight="bold", color=INK, ha="right", va="center")
    ba = cv[f"random_forest|{main}"]["test"]["balanced_accuracy"]
    head.text(1.0, 0.05, f"vs EMST labels, held-out 2 km blocks (all {len(classes)} classes: balanced accuracy {ba:.2f})",
              fontsize=12, color=MUTED, ha="right", va="center")
    fig.legend(handles=_legend_handles(classes), loc="lower left", ncol=len(classes), frameon=False,
               bbox_to_anchor=(0.03, 0.01), fontsize=11.5)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def class_curves(curves, classes, path, year):
    panels = [("NDVI", "NDVI (greenness)"), ("NDRE", "NDRE (red-edge index)"),
              ("VH", "Sentinel-1 VH backscatter (dB)"), ("VHVV", "Sentinel-1 VH/VV ratio (dB)")]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9.5), constrained_layout=True)
    for ax, (var, title) in zip(axes.ravel(), panels):
        d = curves[var]
        for c in classes:
            name = CLASSES[c][0]
            if name in d:
                _curve(ax, d[name], CLASSES[c][1], name)
        for k, q in d.items():
            if "lidar" in k:
                col = CORE_COLOR["Grassland"] if k.startswith("Grassland") else CLASSES[classes[0]][1]
                _curve(ax, q, col, k, dashed=True)
        _month_axis(ax)
        ax.set_title(title, loc="left")
    h, lab = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=4, frameon=False, fontsize=9.5, bbox_to_anchor=(0.5, -0.07))
    fig.suptitle(f"Monthly medians per EMST class, {year} (shading: middle 50 % of 20,000 pixels per class; "
                 "dashed: lidar-filtered 'core' pixels)", color=MUTED, fontsize=11)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def model_comparison(cv, configs, path, clustered, cluster_px, main, metric="balanced_accuracy"):
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True,
                                  gridspec_kw={"width_ratios": [1.6, 1]})
    models = [("random_forest", "Random Forest"), ("hist_gradient_boosting", "Gradient boosting")]
    rows = [(cfg, m, ml) for cfg in configs for m, ml in models]
    off = {"random_cv": -0.22, "spatial_cv": 0.0, "test": 0.22}
    for i, (cfg, m, ml) in enumerate(rows):
        for sc, o in off.items():
            if sc not in cv[f"{m}|{cfg}"]:
                continue  # gradient-boosting CV is run for the main configuration only
            v = cv[f"{m}|{cfg}"][sc][metric]
            lab, col, mk = SCHEME[sc]
            ax.plot([0, v], [i + o, i + o], color=GRID, linewidth=1, zorder=1)
            ax.plot(v, i + o, marker=mk, color=col, markersize=7, linestyle="none", zorder=3,
                    label=lab if i == 0 else None)
        t = cv[f"{m}|{cfg}"]["test"][metric]
        ax.text(t + 0.01, i + 0.22, f"{t:.3f}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(rows)), [f"{cfg} | {ml}" for cfg, _, ml in rows], fontsize=9.5)
    ax.set_ylim(len(rows) - 0.5, -0.6)
    lo = min(cv[f"{m}|{c}"][s][metric] for c, m, _ in rows for s in off if s in cv[f"{m}|{c}"])
    hi = max(cv[f"{m}|{c}"][s][metric] for c, m, _ in rows for s in off if s in cv[f"{m}|{c}"])
    ax.set_xlim(max(0, lo - 0.05), min(1.0, hi + 0.06))
    ax.set_xlabel("Balanced accuracy vs EMST labels (axis zoomed)")
    ax.set_title("Which sensors help? (scattered-pixel training sample)", loc="left")
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, loc="lower right", fontsize=9)

    labels_ = ["scattered\npixels", f"{cluster_px}x{cluster_px}-pixel\npatches"]
    scat = cv[f"random_forest|{main}"]
    for j, d in enumerate([scat, clustered]):
        for sc, o in off.items():
            lab, col, mk = SCHEME[sc]
            ax2.bar(j + o, d[sc][metric], width=0.2, color=col, label=lab if j == 0 else None)
            ax2.text(j + o, d[sc][metric] + 0.005, f"{d[sc][metric]:.2f}", ha="center", fontsize=9)
    ax2.set_xticks([0, 1], labels_)
    vals = [d[sc][metric] for d in (scat, clustered) for sc in off]
    ax2.set_ylim(max(0, min(vals) - 0.1), min(1, max(vals) + 0.05))
    ax2.set_ylabel(f"Balanced accuracy (Random Forest, {main})")
    ax2.set_title("Sampling design and random CV", loc="left")
    ax2.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax2.set_axisbelow(True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def confusion_figure(n, classes, ua, pa, path, title):
    n = np.asarray(n)
    share = n / np.maximum(n.sum(1, keepdims=True), 1)
    names = [CLASSES[c][0] for c in classes]
    fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
    ax.imshow(share, cmap="Blues", vmin=0, vmax=1)
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, f"{n[i, j]}", ha="center", va="center", fontsize=10,
                    color="white" if share[i, j] > 0.55 else INK)
    ax.set_xticks(range(len(classes)), [f"{nm}\nPA {p:.2f}" for nm, p in zip(names, pa)], rotation=30, ha="right")
    ax.set_yticks(range(len(classes)), [f"{nm}  UA {u:.2f}" for nm, u in zip(names, ua)])
    ax.set_xlabel("Reference (TPWD EMST label)")
    ax.set_ylabel("Map (Random Forest)")
    ax.set_title(title, loc="left", fontsize=11)
    ax.spines[:].set_visible(False)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def importance_figure(pi, path):
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), constrained_layout=True)
    for ax, (by, title) in zip(axes, [("sensor_season", "By sensor and season"), ("month", "By month (both sensors)")]):
        g = pi[by]["groups"]
        names = list(g)
        if by == "month":
            names = sorted(names)
        else:
            names = sorted(names, key=lambda k: g[k]["mean_drop"])
        y = np.arange(len(names))
        ax.barh(y, [g[k]["mean_drop"] for k in names], xerr=[g[k]["sd"] for k in names],
                color="#2f5d8a", height=0.7, error_kw={"ecolor": MUTED, "capsize": 3})
        ax.set_yticks(y, [k[3:] if by == "month" else k for k in names])
        if by == "month":
            ax.invert_yaxis()
        ax.set_xlabel("Drop in balanced accuracy when the group is shuffled")
        ax.set_title(f"{title}\nmodel: {pi[by]['model'].replace('random_forest|', 'Random Forest, ')}", loc="left")
        ax.xaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _stretch(rgb):
    a = np.moveaxis(np.asarray(rgb, dtype="float32"), 0, -1)
    lo, hi = np.percentile(a, 2), np.percentile(a, 98)
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)


def naip_inset(chip, ext, emst_w, pred_w, frac_w, max_w, classes, path, naip_id):
    """NAIP 60 cm photo with the 10 m pixel grid, next to the EMST label, the map and lidar cover."""
    fig, axes = plt.subplots(1, 4, figsize=(19, 5.6), constrained_layout=True)
    x0, x1, y0, y1 = ext
    axes[0].imshow(_stretch(chip), extent=(0, x1 - x0, 0, y1 - y0))
    for v in np.arange(0, x1 - x0 + 1, 10):
        axes[0].axvline(v, color="white", linewidth=0.35, alpha=0.7)
        axes[0].axhline(v, color="white", linewidth=0.35, alpha=0.7)
    axes[0].add_patch(Rectangle((140, 140), 10, 10, fill=False, edgecolor="#ff4040", linewidth=1.5))
    axes[0].set_title("NAIP 60 cm photo, 10 m grid (white)\nred square = one Sentinel pixel", loc="left", fontsize=11)
    ext_m = (0, x1 - x0, 0, y1 - y0)
    for ax, img, title in ((axes[1], emst_w, "EMST label"), (axes[2], pred_w, "Random Forest map (S1 + S2)")):
        cmap, norm, lut = class_cmap(classes)
        ax.imshow(_index_image(img, lut), cmap=cmap, norm=norm, interpolation="nearest", extent=ext_m)
        ax.set_title(title, loc="left", fontsize=11)
    im = axes[3].imshow(100 * frac_w, cmap="Greens", vmin=0, vmax=100, interpolation="nearest", extent=ext_m)
    fig.colorbar(im, ax=axes[3], shrink=0.8, label="% of 2 m lidar cells taller than 1 m")
    axes[3].set_title("Lidar woody cover per 10 m pixel", loc="left", fontsize=11)
    for ax in axes:
        ax.set_xlabel("m")
    fig.legend(handles=_legend_handles(classes), loc="lower center", ncol=len(classes), frameon=False,
               bbox_to_anchor=(0.5, -0.08), fontsize=10)
    fig.suptitle(f"What a 10 m pixel sees: 300 m x 300 m window ({naip_id})", color=MUTED, fontsize=11)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def naip_chips(chips, exts, xy, titles, path, res):
    """Spot-check chips: NAIP around sampled pixels, the 10 m pixel outlined in red."""
    n = len(chips)
    ncol = 6
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.1 * ncol, 3.4 * nrow), constrained_layout=True)
    for ax in np.ravel(axes):
        ax.axis("off")
    for ax, chip, ext, (x, y), t in zip(np.ravel(axes), chips, exts, xy, titles):
        x0, x1, y0, y1 = ext
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        half = 40.0  # show 80 m around the pixel
        a = np.asarray(chip)
        if a.shape[1] < 10:
            continue
        pxl = a.shape[1] / (x1 - x0)
        i0, i1 = int((cx - half - x0) * pxl), int((cx + half - x0) * pxl)
        sub = a[:, i0:i1, i0:i1]
        ax.imshow(_stretch(sub), extent=(-half, half, -half, half))
        ax.add_patch(Rectangle((x - cx - res / 2, y - cy - res / 2), res, res, fill=False, edgecolor="#ff3030",
                               linewidth=1.6))
        ax.set_title(t.replace(" | ", "\n", 1), fontsize=8.5)
    fig.suptitle("NAIP 2020 (60 cm) around held-out sample pixels; red square = the 10 m pixel; 80 m across",
                 color=MUTED, fontsize=11)
    fig.savefig(path, dpi=80, bbox_inches="tight")
    plt.close(fig)


def lidar_check_figure(frac, emst, valid, test_flat, pred_test, classes, path):
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5), constrained_layout=True, sharey=True)
    for ax, title, getter in (
        (axes[0], "By EMST label (whole box)", lambda c: frac[valid & (emst == c)]),
        (axes[1], "By mapped class (held-out blocks, S1 + S2 model)", lambda c: frac.ravel()[test_flat][pred_test == c]),
    ):
        data_ = [100 * getter(c) for c in classes]
        bp = ax.boxplot(data_, vert=True, patch_artist=True, showfliers=False, widths=0.6)
        for patch, c in zip(bp["boxes"], classes):
            patch.set_facecolor(CLASSES[c][1])
            patch.set_alpha(0.85)
        for med in bp["medians"]:
            med.set_color(INK)
        ax.axhline(25, color="#c4661f", linestyle="--", linewidth=1)
        ax.text(len(classes) + 0.45, 26, "25 % canopy", color="#c4661f", fontsize=9, ha="right")
        ax.set_xticks(range(1, len(classes) + 1), [CLASSES[c][0].replace(" (", "\n(").replace(" / ", " /\n") for c in classes],
                      rotation=0, fontsize=8.5)
        ax.set_title(title, loc="left")
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    axes[0].set_ylabel("Lidar woody cover in the 10 m pixel (%)\n(share of 2 m cells taller than 1 m)")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
