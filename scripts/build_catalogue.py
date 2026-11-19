"""Build the static STAC catalogue in docs/stac/ from the studies listed in catalogue/sources.yaml.

For each study: one STAC Collection. For each layer: one Item with
  vector layers -> GeoParquet (data) and GeoJSON (data), EPSG:4326
  raster layers -> Cloud-Optimised GeoTIFF (data) and a PNG quick-look in EPSG:4326 (overview)
Every local asset carries file:size and file:checksum (sha2-256 multihash). A converted file larger than
max_file_mb is not copied; its asset links to the file in the source repository instead.

Writes docs/stac/**, docs/data/catalogue_stats.json and docs/data/search_index.json.
The source repositories are only read.

    python scripts/build_catalogue.py
"""
import calendar
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pystac
import rasterio
import shapely
from pystac.extensions.file import FileExtension
from pystac.extensions.projection import ProjectionExtension
from pystac.extensions.table import TableExtension
from rasterio.warp import Resampling, reproject, transform_bounds, transform_geom
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from shapely.geometry import box, mapping, shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import converters  # noqa: E402
from common import DATA, DOCS, ROOT, SITE_URL, STAC, load_sources, multihash_sha256  # noqa: E402

MEDIA = {
    "geoparquet": "application/vnd.apache.parquet",
    "geojson": "application/geo+json",
    "cog": "image/tiff; application=geotiff; profile=cloud-optimized",
    "preview": "image/png",
    "source_tif": "image/tiff; application=geotiff",
}
LICENCE_URL = {"CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/", "MIT": "https://opensource.org/license/mit"}
PREVIEW_MAX_PX = 480


# ---------------------------------------------------------------- dates
def _resolve(value, repo):
    """A date string, or "json:<file>#<a.b>" read from a JSON file in the source repository."""
    if isinstance(value, str) and value.startswith("json:"):
        f, key = value[5:].split("#", 1)
        v = json.loads((repo / f).read_text(encoding="utf-8"))
        rest = key
        while rest:  # keys may themselves contain dots: take the longest key that matches at each level
            k = max((k for k in v if rest == k or rest.startswith(k + ".")), key=len)
            v, rest = v[k], rest[len(k) + 1:]
        return str(v)
    return None if value is None else str(value)


def _to_dt(s, end=False):
    """YYYY, YYYY-MM or YYYY-MM-DD to a UTC datetime; an end date covers the whole year, month or day."""
    parts = [int(p) for p in s[:10].split("-")]
    if len(parts) == 1:
        parts += [12 if end else 1]
    if len(parts) == 2:
        parts += [calendar.monthrange(parts[0], parts[1])[1] if end else 1]
    d = dt.datetime(*parts, tzinfo=dt.timezone.utc)
    return d.replace(hour=23, minute=59, second=59) if end else d


def layer_period(layer, source, repo, gdf=None):
    if layer.get("period_property"):
        vals = gdf[layer["period_property"]].dropna().astype(str)
        starts = [_to_dt(v.split("/")[0]) for v in vals]
        ends = [_to_dt(v.split("/")[1]) for v in vals]  # stated end kept as given (start of that day)
        return min(starts), max(ends).replace(hour=0, minute=0, second=0)
    start = _resolve(layer.get("start", source["period"]["start"]), repo)
    end = _resolve(layer.get("end", source["period"]["end"]), repo)
    if not start or not end:
        raise ValueError(f"{source['id']}/{layer['id']}: no start or end date")
    return _to_dt(start), _to_dt(end, end=True)


# ---------------------------------------------------------------- git provenance
def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def provenance(repo, gh_repo_url):
    commit = _git(repo, "rev-parse", "HEAD")
    pushed = bool(_git(repo, "branch", "-r", "--contains", "HEAD")) if commit else False
    return {"commit": commit, "branch": _git(repo, "branch", "--show-current"), "on_remote": pushed,
            "date": _git(repo, "log", "-1", "--format=%cs")}


def source_url(gh, prov, rel):
    ref = prov["commit"] if prov["on_remote"] else "main"
    return f"{gh}/blob/{ref}/{rel}"


# ---------------------------------------------------------------- assets
def add_file_info(asset, path):
    fe = FileExtension.ext(asset, add_if_missing=True)
    fe.size = path.stat().st_size
    fe.checksum = multihash_sha256(path)


def footprint(geom, max_coords=1500):
    """Item geometry: the union of the features, simplified until it is small enough for the item JSON."""
    if geom.geom_type in ("Point", "MultiPoint"):  # points do not simplify: use their convex hull
        return geom.convex_hull if shapely.get_num_coordinates(geom) > 1 else geom
    g = shapely.make_valid(geom)
    tol = 0.0
    while shapely.get_num_coordinates(g) > max_coords and tol < 0.5:
        tol = 0.002 if tol == 0 else tol * 2
        g = shapely.make_valid(geom.simplify(tol, preserve_topology=True))
    return g if shapely.get_num_coordinates(g) <= max_coords else geom.convex_hull


def vector_item(layer, source, repo, item_dir):
    src = repo / layer["file"]
    if layer.get("converter"):
        gdf = getattr(converters, layer["converter"])(src, **layer.get("converter_args", {}))
    else:
        gdf = gpd.read_file(src)
    if gdf.crs is None:  # GeoJSON without a crs member is WGS 84 (RFC 7946)
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].reset_index(drop=True)
    invalid = int((~gdf.geometry.is_valid).sum())
    if invalid:
        gdf["geometry"] = shapely.make_valid(gdf.geometry.values)
    start, end = layer_period(layer, source, repo, gdf)

    item_dir.mkdir(parents=True, exist_ok=True)
    pq, gj = item_dir / f"{layer['id']}.parquet", item_dir / f"{layer['id']}.geojson"
    gdf.to_parquet(pq, index=False, schema_version="1.1.0")
    out = gdf.copy()
    for c in out.columns:
        if c != "geometry" and str(out[c].dtype).startswith("datetime"):
            out[c] = out[c].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    gj.write_text(out.to_json(na="null", drop_id=True), encoding="utf-8")

    union = shapely.union_all(gdf.geometry.values)
    geom = footprint(union)
    item = pystac.Item(id=layer["id"], geometry=mapping(geom), bbox=[float(x) for x in gdf.total_bounds],
                       datetime=None, start_datetime=start, end_datetime=end,
                       properties={"title": layer["title"], "description": " ".join(layer["description"].split())})
    te = TableExtension.ext(item, add_if_missing=True)
    te.row_count = len(gdf)
    te.columns = [pystac.extensions.table.Column({"name": c, "type": str(gdf[c].dtype)}) for c in gdf.columns]
    item.properties["geocat:kind"] = "vector"
    item.properties["geocat:invalid_geometries_repaired"] = invalid
    assets = {"geoparquet": (pq, "GeoParquet", MEDIA["geoparquet"]), "geojson": (gj, "GeoJSON", MEDIA["geojson"])}
    return item, assets, {"features": len(gdf)}


def raster_preview(src_path, png, bbox4326):
    """Quick-look PNG on an EPSG:4326 grid that spans bbox4326, coloured with viridis between the 2nd and 98th
    percentiles, no-data transparent. Returns the value range used for the colours."""
    import matplotlib
    from PIL import Image
    with rasterio.open(src_path) as s:
        a = s.read(1, masked=True).astype("float64")
        w, so, e, n = bbox4326
        aspect = (n - so) / (e - w)
        width = min(PREVIEW_MAX_PX, max(s.width, 64))
        height = max(1, int(round(width * aspect)))
        dst = np.full((height, width), np.nan)
        src_arr = a.filled(np.nan)
        reproject(src_arr, dst, src_transform=s.transform, src_crs=s.crs, src_nodata=np.nan,
                  dst_transform=rasterio.transform.from_bounds(w, so, e, n, width, height), dst_crs="EPSG:4326",
                  dst_nodata=np.nan, resampling=Resampling.nearest)
    vals = dst[np.isfinite(dst)]
    lo, hi = (float(np.percentile(vals, 2)), float(np.percentile(vals, 98))) if vals.size else (0.0, 1.0)
    if hi <= lo:
        hi = lo + 1e-9
    rgba = matplotlib.colormaps["viridis"](np.clip((dst - lo) / (hi - lo), 0, 1), bytes=True)
    rgba[~np.isfinite(dst)] = 0
    Image.fromarray(rgba, "RGBA").save(png, optimize=True)
    return lo, hi


def raster_item(layer, source, repo, item_dir):
    src = repo / layer["file"]
    start, end = layer_period(layer, source, repo)
    item_dir.mkdir(parents=True, exist_ok=True)
    cog = item_dir / f"{layer['id']}.tif"
    with rasterio.open(src) as s:
        crs, shape_, tr, bounds = s.crs, (s.height, s.width), s.transform, s.bounds
        nodata, dtype, tags = s.nodata, s.dtypes[0], s.tags()
    profile = cog_profiles.get("deflate")
    profile.update({"predictor": 3 if dtype.startswith("float") else 2})
    cog_translate(str(src), str(cog), profile, in_memory=True, quiet=True, overview_resampling="average")
    if crs.to_epsg() == 4326:
        geom = box(*bounds)
    else:  # densified outline of the grid, so the footprint follows the projected edges
        edge = box(*bounds).segmentize(max(bounds.right - bounds.left, bounds.top - bounds.bottom) / 20)
        geom = shape(transform_geom(crs, "EPSG:4326", mapping(edge), precision=6))
    bbox = [float(x) for x in (transform_bounds(crs, "EPSG:4326", *bounds, densify_pts=21) if crs.to_epsg() != 4326 else bounds)]
    png = item_dir / f"{layer['id']}.preview.png"
    lo, hi = raster_preview(cog, png, bbox)
    item = pystac.Item(id=layer["id"], geometry=mapping(geom), bbox=bbox, datetime=None,
                       start_datetime=start, end_datetime=end,
                       properties={"title": layer["title"], "description": " ".join(layer["description"].split())})
    pe = ProjectionExtension.ext(item, add_if_missing=True)
    pe.code = f"EPSG:{crs.to_epsg()}"
    pe.shape = list(shape_)
    pe.transform = [tr.a, tr.b, tr.c, tr.d, tr.e, tr.f]
    pe.bbox = [bounds.left, bounds.bottom, bounds.right, bounds.top]
    item.properties.update({
        "geocat:kind": "raster",
        "geocat:band_description": tags.get("description", ""),
        "geocat:data_type": dtype,
        "geocat:nodata": None if nodata is None or (isinstance(nodata, float) and np.isnan(nodata)) else nodata,
        "geocat:nodata_is_nan": bool(nodata is not None and isinstance(nodata, float) and np.isnan(nodata)),
        "geocat:preview_range": [round(lo, 4), round(hi, 4)],
        "geocat:preview_colormap": "viridis",
    })
    assets = {"cog": (cog, "Cloud-Optimised GeoTIFF", MEDIA["cog"]), "preview": (png, "Quick-look (EPSG:4326)", MEDIA["preview"])}
    return item, assets, {}


# ---------------------------------------------------------------- discovery
def discover_layers(source, repo, defaults):
    layers = []
    for folder in source.get("discover", defaults.get("discover", [])):
        base = repo / folder
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            kind = {".geojson": "vector", ".tif": "raster", ".tiff": "raster"}.get(f.suffix.lower())
            if kind is None:
                continue
            rel = f.relative_to(repo).as_posix()
            lid = f.stem.lower().replace("_", "-").replace(".", "-")
            layers.append({"id": lid, "title": f.stem.replace("_", " "), "kind": kind, "file": rel,
                           "description": f"{rel} from the {source['repo']} repository (found automatically)."})
    return layers


# ---------------------------------------------------------------- main
def main():
    defaults, sources = load_sources()
    max_file = defaults["max_file_mb"] * 1024 * 1024
    user = defaults["github_user"]
    if STAC.exists():
        shutil.rmtree(STAC)
    STAC.mkdir(parents=True)
    DATA.mkdir(parents=True, exist_ok=True)

    root = pystac.Catalog(
        id="open-geodata-catalogue",
        title="Open geodata catalogue",
        description=("Spatial outputs of David Oloyede's open studies (hydrology, groundwater, urban heat, coastal "
                     "sealing), as one STAC collection per study. Data keep the licence and limits stated by each study."),
    )
    root.add_link(pystac.Link("about", SITE_URL, "text/html", "Catalogue website"))

    stats = {"stac_version": pystac.get_stac_version(), "collections": [], "pending": [],
             "max_file_mb": defaults["max_file_mb"], "max_docs_mb": defaults["max_docs_mb"]}
    search = []
    bytes_by_format = {"geoparquet": 0, "geojson": 0, "cog": 0, "preview": 0}
    files_by_format = {k: 0 for k in bytes_by_format}
    linked_only = []

    for source in sources:
        repo = Path(source["path"])
        gh = f"https://github.com/{user}/{source['repo']}"
        page = f"https://{user}.github.io/{source['repo']}/"
        layers = source.get("layers") or (discover_layers(source, repo, defaults) if repo.exists() else [])
        if not repo.exists() or not layers:
            reason = "repository not found" if not repo.exists() else "no GeoJSON or GeoTIFF outputs found"
            stats["pending"].append({"id": source["id"], "repo": source["repo"], "reason": reason})
            print(f"skip {source['id']}: {reason}")
            continue
        lic = source["licence"]
        problem = None
        if not (repo / lic["stated_in"]).exists():
            problem = f"licence statement {lic['stated_in']} not found"
        elif not source.get("layers") and not all(source.get("period", {}).get(k) for k in ("start", "end")):
            problem = "outputs found, but no study period set in sources.yaml"
        if problem:
            stats["pending"].append({"id": source["id"], "repo": source["repo"], "reason": problem})
            print(f"skip {source['id']}: {problem}")
            continue
        prov = provenance(repo, gh)
        coll_dir = STAC / source["id"]
        items, cstats = [], {"id": source["id"], "repo": source["repo"], "title": source["title"], "page": page,
                             "github": gh, "items": 0, "vector": 0, "raster": 0, "features": 0, "files": 0, "bytes": 0,
                             "linked_only": 0, "commit": prov["commit"][:7], "commit_date": prov["date"],
                             "branch": prov["branch"], "licence_data": lic["data"], "licence_code": lic["code"],
                             "items_own_licence": []}
        for layer in layers:
            item_dir = coll_dir / layer["id"]
            build = vector_item if layer["kind"] == "vector" else raster_item
            item, assets, extra = build(layer, source, repo, item_dir)
            for key, (path, title, media) in assets.items():
                size = path.stat().st_size
                if size > max_file and key != "preview":
                    path.unlink()
                    src = repo / layer["file"]
                    asset = pystac.Asset(href=source_url(gh, prov, layer["file"]), title=f"{title} (not copied: "
                                         f"{size / 1048576:.1f} MB; source file in the study repository)",
                                         media_type=MEDIA["source_tif"] if layer["kind"] == "raster" else None,
                                         roles=["data"])
                    item.add_asset(key, asset)
                    add_file_info(asset, src)
                    linked_only.append(f"{source['id']}/{layer['id']}/{key}")
                    cstats["linked_only"] += 1
                else:
                    asset = pystac.Asset(href=f"./{path.name}", title=title, media_type=media,
                                         roles=["overview"] if key == "preview" else ["data"])
                    item.add_asset(key, asset)
                    add_file_info(asset, path)
                    bytes_by_format[key] += size
                    files_by_format[key] += 1
                    cstats["files"] += 1
                    cstats["bytes"] += size
            item.add_link(pystac.Link("via", source_url(gh, prov, layer["file"]), "text/html",
                                      f"Source file in {source['repo']} at commit {prov['commit'][:7]}"))
            item.add_link(pystac.Link("about", page, "text/html", "Study page"))
            if layer.get("licence"):  # an item whose licence differs from its collection's
                item.properties["license"] = layer["licence"]
                cstats["items_own_licence"].append({"item": layer["id"], "licence": layer["licence"]})
                if layer.get("licence_url"):
                    item.add_link(pystac.Link("license", layer["licence_url"], "text/html", layer["licence"]))
            item.properties["geocat:source_file"] = layer["file"]
            item.properties["geocat:source_commit"] = prov["commit"]
            items.append(item)
            cstats["items"] += 1
            cstats[layer["kind"]] += 1
            cstats["features"] += extra.get("features", 0)
            cstats["converted"] = cstats.get("converted", 0) + bool(layer.get("converter"))
            search.append({"collection": source["id"], "collection_title": source["title"], "id": item.id,
                           "title": item.properties["title"], "description": item.properties["description"],
                           "kind": layer["kind"], "bbox": [round(x, 4) for x in item.bbox],
                           "start": item.properties["start_datetime"][:10], "end": item.properties["end_datetime"][:10],
                           "features": extra.get("features"), "keywords": source.get("keywords", []),
                           "page": f"items/{source['id']}/{item.id}.html"})

        bboxes = np.array([i.bbox for i in items])
        sbox = [float(bboxes[:, 0].min()), float(bboxes[:, 1].min()), float(bboxes[:, 2].max()), float(bboxes[:, 3].max())]
        starts = [dt.datetime.fromisoformat(i.properties["start_datetime"].replace("Z", "+00:00")) for i in items]
        ends = [dt.datetime.fromisoformat(i.properties["end_datetime"].replace("Z", "+00:00")) for i in items]
        licence = lic["data"]
        coll = pystac.Collection(
            id=source["id"], title=source["title"], description=" ".join(source["description"].split()),
            extent=pystac.Extent(pystac.SpatialExtent([sbox]), pystac.TemporalExtent([[min(starts), max(ends)]])),
            license=licence, keywords=source.get("keywords", []),
            providers=[
                pystac.Provider(f"{defaults['author']}", roles=[pystac.ProviderRole.PRODUCER, pystac.ProviderRole.PROCESSOR,
                                                                 pystac.ProviderRole.LICENSOR], url=gh),
                pystac.Provider("GitHub Pages", roles=[pystac.ProviderRole.HOST], url=SITE_URL),
            ],
        )
        coll.add_link(pystac.Link("about", page, "text/html", "Study page"))
        coll.add_link(pystac.Link("via", gh, "text/html", "Study repository"))
        coll.add_link(pystac.Link("license", f"{gh}/blob/main/{lic['stated_in']}", "text/html",
                                  f"Licence statement ({lic['stated_in']})"))
        if licence in LICENCE_URL:
            coll.add_link(pystac.Link("license", LICENCE_URL[licence], "text/html", licence))
        coll.extra_fields["geocat:code_licence"] = lic["code"]
        if lic.get("note"):
            coll.extra_fields["geocat:licence_note"] = lic["note"]
        coll.extra_fields["geocat:source_commit"] = prov["commit"]
        coll.extra_fields["geocat:source_branch"] = prov["branch"]
        coll.extra_fields["geocat:source_commit_date"] = prov["date"]
        coll.extra_fields["geocat:source_commit_on_remote"] = prov["on_remote"]
        for it in items:
            coll.add_item(it)
        root.add_child(coll)
        cstats["bbox"] = [round(x, 4) for x in sbox]
        cstats["start"], cstats["end"] = min(starts).date().isoformat(), max(ends).date().isoformat()
        cstats["licence_note"] = lic.get("note", "")
        stats["collections"].append(cstats)
        print(f"{source['id']}: {len(items)} items")

    root.normalize_hrefs(str(STAC))
    root.validate_all()
    root.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)

    cs = stats["collections"]
    stats.update({
        "n_collections": len(cs), "n_items": sum(c["items"] for c in cs),
        "n_vector_items": sum(c["vector"] for c in cs), "n_raster_items": sum(c["raster"] for c in cs),
        "n_features": sum(c["features"] for c in cs), "n_data_files": sum(files_by_format.values()),
        "bytes_data_files": sum(bytes_by_format.values()), "bytes_by_format": bytes_by_format,
        "files_by_format": files_by_format, "linked_only": linked_only, "n_pending": len(stats["pending"]),
        "n_sources_configured": len(sources), "n_converted": sum(c.get("converted", 0) for c in cs),
        "largest_file_bytes": max((p.stat().st_size for p in STAC.rglob("*") if p.is_file()), default=0),
        "bytes_stac_dir": sum(p.stat().st_size for p in STAC.rglob("*") if p.is_file()),
        "n_stac_json": sum(1 for _ in STAC.rglob("*.json")),
        "start": min(c["start"] for c in cs), "end": max(c["end"] for c in cs),
        "built": dt.date.today().isoformat(),
    })
    (DATA / "catalogue_stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (DATA / "search_index.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    docs_mb = sum(p.stat().st_size for p in DOCS.rglob("*") if p.is_file()) / 1048576
    if docs_mb > defaults["max_docs_mb"]:
        raise SystemExit(f"docs/ is {docs_mb:.1f} MB, over the {defaults['max_docs_mb']} MB limit")
    print(f"{stats['n_collections']} collections, {stats['n_items']} items, {stats['n_data_files']} data files, "
          f"{stats['bytes_data_files'] / 1048576:.2f} MB; docs/ {docs_mb:.1f} MB")


if __name__ == "__main__":
    main()
