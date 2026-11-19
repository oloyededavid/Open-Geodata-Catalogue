"""Turn the studies' non-GIS outputs (JSON written for their web pages) into vector layers.

Each function takes the source file path and returns a GeoDataFrame in EPSG:4326. A layer in
catalogue/sources.yaml names one of these with `converter:`.
"""
import json

import geopandas as gpd
from shapely.geometry import box


def _cell(lon, lat, size):
    h = size / 2
    return box(lon - h, lat - h, lon + h, lat + h)


def hydro_return_levels(path):
    """Observational-Hydrology-Extremes docs/data/cells.json: per study area, the 0.25-degree cell centres
    ([lon, lat]) and CHIRPS 1985-2014 Rx1day return levels (mm) for each return period."""
    d = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for area, v in d.items():
        periods = sorted(v["chirps_rl"], key=int)
        for i, (lon, lat) in enumerate(v["cells"]):
            r = {"area": area, "cell_lon": lon, "cell_lat": lat}
            for t in periods:
                r[f"rl_{t}yr_mm"] = v["chirps_rl"][t][i]
            r["geometry"] = _cell(lon, lat, 0.25)
            rows.append(r)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def grace_trend_cells(path):
    """Groundwater-Storage-Gravimetry docs/data/grace_cells.json: 1-degree cell centres with the storage trend
    (mm per year). Cells without a trend are left out; `in_main_area` marks the cells the study used for its
    main area (the `main_cells` list)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    size = float(d["cell_deg"])
    main = {(float(a), float(o)) for a, o in d["main_cells"]}
    rows = [{"cell_lat": c["lat"], "cell_lon": c["lon"], "trend_mm_per_yr": c["trend"],
             "in_main_area": (float(c["lat"]), float(c["lon"])) in main,
             "geometry": _cell(c["lon"], c["lat"], size)}
            for c in d["cells"] if c["trend"] is not None]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def moz_district_access(path, columns_prefix="A_"):
    """Mozambique-Health-Access docs/data/districts.geojson joined with docs/data/district_access.csv on district
    name and province. Only the population, `compared` and the list-A columns (public-sector list of Maina et al.,
    CC BY 4.0 as the study states) are kept; results that use OpenStreetMap facilities fall under the ODbL and are
    left to the study page."""
    import pandas as pd
    g = gpd.read_file(path)
    d = pd.read_csv(path.parent / "district_access.csv")
    keep = ["district", "province", "population", "compared"] + [c for c in d.columns if c.startswith(columns_prefix)]
    m = g.merge(d[keep], left_on=["name", "province"], right_on=["district", "province"], how="left", validate="1:1")
    if m["population"].isna().any():
        raise ValueError("district_access.csv does not match districts.geojson")
    return m.drop(columns="district")


def moz_facilities(path, lists=("A", "H")):
    """Mozambique-Health-Access docs/data/facilities.csv as points (lon, lat in WGS 84), for the given lists."""
    import pandas as pd
    f = pd.read_csv(path)
    f = f[f["list"].isin(lists)].reset_index(drop=True)
    return gpd.GeoDataFrame(f, geometry=gpd.points_from_xy(f["lon"], f["lat"]), crs="EPSG:4326")
