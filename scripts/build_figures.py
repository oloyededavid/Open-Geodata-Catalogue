"""Figures for the design note (docs/about.html), drawn from files the build already wrote:

    fig1_flow         how a layer goes from a study repository to the static catalogue and to the service
    fig2_footprints   where each collection's items lie (docs/data/footprints.geojson on docs/assets/basemap.geojson)
    fig3_contents     items and megabytes per collection (docs/data/catalogue_stats.json)

Each is written to docs/assets/figures/ for desktop and phone (WebP).

    python scripts/build_figures.py
"""
import json
import sys
import textwrap
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DOCS  # noqa: E402

OUT = DOCS / "assets" / "figures"
DPI, DPI_PHONE = 220, 180  # build_page.py caps each image at its size in CSS pixels (96 per inch), so text keeps its point size
INK, INK2, RULE, LAND = "#1d1d1b", "#5f5e5a", "#c9c8c2", "#f1f0ec"
# one colour per collection, in catalogue order; Okabe and Ito's set, which stays apart for the common colour-vision types
COLOURS = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#6b6a64"]
SHORT = {
    "observational-hydrology-extremes": "Hydrological extremes, Nigeria",
    "ogun-catchment-coast-observatory": "Ogun catchment observatory",
    "oueme-ogun-groundwater-recharge": "Ouémé and Ogun recharge",
    "groundwater-storage-gravimetry": "Water storage, Lake Chad basin",
    "lagos-urban-heat-analytics": "Lagos urban heat",
    "coastal-hydrogeology-modeling": "Sealing, Lekki–Epe, Lagos",
    "mozambique-health-access": "Mozambique health access",
}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": RULE})


def save(fig, name, phone):
    OUT.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=DPI_PHONE if phone else DPI, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    plt.close(fig)
    Image.open(buf).save(OUT / f"{name}{'_phone' if phone else ''}.webp", "WEBP", quality=88, method=6)


def stats():
    return json.loads((DATA / "catalogue_stats.json").read_text(encoding="utf-8"))


def box(ax, x, y, w, h, title, lines, fill="white", edge=RULE, small=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12", facecolor=fill,
                                edgecolor=edge, linewidth=1))
    ax.text(x + 0.18, y + h - 0.22, title, fontsize=8.8 if small else 9.5, fontweight="bold", va="top", color=INK)
    ax.text(x + 0.18, y + h - 0.62, "\n".join(lines), fontsize=7.4 if small else 8.2, va="top", color=INK2, linespacing=1.45)


def arrow(ax, a, b, label=None, off=(0, 0.12)):
    ax.annotate("", b, a, arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1, shrinkA=2, shrinkB=2,
                                          mutation_scale=10))
    if label:
        ax.text((a[0] + b[0]) / 2 + off[0], (a[1] + b[1]) / 2 + off[1], label, fontsize=7.6, color=INK2,
                ha="center", va="bottom")


def fig1_flow(phone):
    S = stats()
    n_rep = S["n_collections"]
    src = ("Study repositories", [f"{n_rep} studies included", "docs/data, outputs:", "GeoJSON, GeoTIFF,", "JSON, CSV"])
    cfg = ("sources.yaml", ["one entry per study:", "layers, periods,", "licences"])
    bld = ("build_catalogue.py", ["converts, checksums,", "writes STAC 1.1.0"])
    stac = ("Static catalogue", ["GeoParquet, GeoJSON,", "Cloud-Optimised GeoTIFF,", "STAC JSON with", "relative links"])
    site = ("GitHub Pages", ["browsable website,", "search, maps"])
    pg = ("PostGIS", ["one table per", "vector item"])
    api = ("pygeoapi", ["OGC API Features,", "local or Docker;", "configured by", "build_service_config.py"])
    # one stacked layout for both sizes: a wide one shrinks below reading size in the text column
    fig, ax = plt.subplots(figsize=(5.6, 10.6))
    ax.set_xlim(0, 7.2); ax.set_ylim(0.3, 14.2)
    w, h = 3.4, 2.1
    P = {"src": (0.0, 12.0), "cfg": (3.8, 12.0), "bld": (1.9, 9.2), "stac": (1.9, 6.4), "site": (0.0, 3.4),
         "pg": (3.8, 3.4), "api": (3.8, 0.4)}
    for k, (t, l) in zip(P, (src, cfg, bld, stac, site, pg, api)):
        box(ax, *P[k], w, h, t, l, fill="#f6f6f3" if k == "bld" else "white", small=True)
    arrow(ax, (1.7, 12.0), (2.8, 11.3)); arrow(ax, (5.5, 12.0), (4.4, 11.3))
    arrow(ax, (3.6, 9.2), (3.6, 8.5), "files", off=(0.4, -0.15))
    arrow(ax, (2.6, 6.4), (1.7, 5.5), "build_site.py", off=(-0.95, -0.1))
    arrow(ax, (4.6, 6.4), (5.5, 5.5), "load_postgis.py", off=(1.1, -0.1))
    arrow(ax, (5.5, 3.4), (5.5, 2.5), "SQL", off=(0.4, -0.15))
    ax.text(0.0, 2.45, textwrap.fill("The tests check the catalogue files, the service and the numbers on the "
                                     "pages. The website and the catalogue share one folder, docs/.", 30),
            fontsize=7.6, color=INK2, va="top")
    ax.axis("off")
    ax.set_aspect("equal")
    save(fig, "fig1_flow", phone)


def fig2_footprints(phone):
    S = stats()
    order = [c["id"] for c in S["collections"]]
    col = dict(zip(order, COLOURS))
    f = gpd.read_file(DATA / "footprints.geojson")
    base = gpd.read_file(DOCS / "assets" / "basemap.geojson")
    zoom = (1.0, 5.6, 4.6, 11.0)  # lon_min, lat_min, lon_max, lat_max: southwest Nigeria and Benin
    if phone:
        fig = plt.figure(figsize=(3.8, 7.6))
        a0 = fig.add_axes([0.0, 0.5, 1.0, 0.47]); a1 = fig.add_axes([0.06, 0.16, 0.88, 0.3])
    else:
        fig = plt.figure(figsize=(7.6, 5.6))
        a0 = fig.add_axes([0.0, 0.2, 0.52, 0.76]); a1 = fig.add_axes([0.56, 0.2, 0.42, 0.72])
    for ax, ext in ((a0, (-19, -36, 53, 38)), (a1, zoom)):
        ax.set_facecolor("white")
        base.plot(ax=ax, facecolor=LAND, edgecolor="white", linewidth=0.6)
        for cid in order:
            g = f[f["collection"] == cid]
            gpd.GeoSeries([g.union_all()], crs=g.crs).plot(ax=ax, facecolor=col[cid], alpha=0.16, edgecolor="none")
            g.boundary.plot(ax=ax, color=col[cid], linewidth=0.9 if ax is a1 else 0.6)
        ax.set_xlim(ext[0], ext[2]); ax.set_ylim(ext[1], ext[3])
        ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel("")
        for s in ax.spines.values():
            s.set_edgecolor(RULE)
    a0.add_patch(Rectangle((zoom[0], zoom[1]), zoom[2] - zoom[0], zoom[3] - zoom[1], fill=False, edgecolor=INK,
                           linewidth=0.8))
    a0.set_title("All collections", loc="left", fontsize=9.5)
    a1.set_title("Southwest Nigeria and Benin (box " + ("above)" if phone else "on the left)"), loc="left", fontsize=9.5)
    for s in a0.spines.values():
        s.set_visible(False)
    counts = {c["id"]: c["items"] for c in S["collections"]}
    handles = [Rectangle((0, 0), 1, 1, facecolor=col[c], alpha=0.5, edgecolor=col[c]) for c in order]
    labels = [f"{SHORT.get(c, c)} ({counts[c]} item{'s' if counts[c] != 1 else ''})" for c in order]
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.0, -0.02 if phone else 0.0),
               ncol=1 if phone else 2, frameon=False, fontsize=7.4 if phone else 8)
    save(fig, "fig2_footprints", phone)


def fig3_contents(phone):
    S = stats()
    C = S["collections"]
    names = [SHORT.get(c["id"], c["id"]) for c in C]
    fig, (a0, a1) = plt.subplots(1, 2, figsize=(3.8, 4.8) if phone else (7.6, 3.9), sharey=True,
                                 gridspec_kw={"width_ratios": (1, 1), "wspace": 0.08 if not phone else 0.12})
    y = range(len(C))
    vec = [c["vector"] for c in C]; ras = [c["raster"] for c in C]
    a0.barh(y, vec, color="#0072B2", height=0.62, label="Vector")
    a0.barh(y, ras, left=vec, color="#E69F00", height=0.62, label="Raster")
    for yi, c in zip(y, C):
        a0.text(c["items"] + 0.4, yi, str(c["items"]), va="center", fontsize=8, color=INK2)
    mbv = [c["bytes"] / 1e6 for c in C]
    a1.barh(y, mbv, color="#9a9992", height=0.62)
    for yi, v in zip(y, mbv):
        a1.text(v + 0.08, yi, f"{v:.1f}", va="center", fontsize=8, color=INK2)
    a0.set_yticks(list(y), [textwrap.fill(n, 16 if phone else 24) for n in names], fontsize=8 if phone else 9)
    a0.invert_yaxis()
    a0.set_xlabel("Items"); a1.set_xlabel("Data files (MB)")
    a0.set_xlim(0, max(c["items"] for c in C) * 1.15); a1.set_xlim(0, max(mbv) * 1.18)
    for ax in (a0, a1):
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", color="#ececE8", linewidth=0.6); ax.set_axisbelow(True)
        ax.tick_params(length=0)
    a1.spines["left"].set_visible(False)
    a0.legend(loc="lower right", frameon=False, fontsize=8)
    save(fig, "fig3_contents", phone)


def main():
    for phone in (False, True):
        fig1_flow(phone)
        fig2_footprints(phone)
        fig3_contents(phone)
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.webp"))))


if __name__ == "__main__":
    main()
