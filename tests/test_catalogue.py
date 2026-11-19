"""The static STAC catalogue in docs/stac: schema validity, links, checksums, sizes, formats and the stats file."""
import json
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import pystac
import pytest
import rasterio
from rio_cogeo.cogeo import cog_validate
from shapely.geometry import box, shape

from common import load_sources, multihash_sha256

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STAC = DOCS / "stac"
MB = 1024 * 1024


def items(catalog):
    return [(c, i) for c in catalog.get_collections() for i in c.get_items()]


def test_validates_against_stac_schemas(catalog):
    assert catalog.validate_all() == len(items(catalog))  # returns the number of items validated
    files = sorted(STAC.rglob("*.json"))
    for path in files:  # the saved files themselves, core schema plus every extension they declare
        d = json.loads(path.read_text())
        pystac.validation.validate_dict(d, href=str(path))
    assert len(files) == 1 + len(list(catalog.get_collections())) + len(items(catalog))


def test_stac_version_and_self_contained(catalog):
    for path in STAC.rglob("*.json"):
        d = json.loads(path.read_text())
        assert d["stac_version"] == "1.1.0", path
        for link in d.get("links", []):
            assert link["rel"] != "self", f"{path}: self link makes the catalogue location-bound"
            href = link["href"]
            if link["rel"] in ("root", "parent", "child", "item", "collection"):
                assert not href.startswith(("http", "/")), f"{path}: {href}"
                assert (path.parent / href).resolve().exists(), f"{path}: {href} missing"
        for a in d.get("assets", {}).values():
            assert not a["href"].startswith("/"), f"{path}: absolute asset path"
            assert "/home/" not in a["href"]


def test_collections_have_licence_providers_links_and_extent(catalog):
    for c in catalog.get_collections():
        assert c.license in ("CC-BY-4.0", "other")
        assert any(lk.rel == "license" for lk in c.links)
        rels = {lk.rel for lk in c.links}
        assert {"about", "via"} <= rels
        assert c.links and [lk for lk in c.links if lk.rel == "about"][0].href.startswith("https://oloyededavid.github.io/")
        roles = {r for p in c.providers for r in p.roles}
        assert {"producer", "licensor", "host"} <= roles
        its = list(c.get_items())
        assert its, c.id
        w, s, e, n = c.extent.spatial.bboxes[0]
        assert min(i.bbox[0] for i in its) == pytest.approx(w) and max(i.bbox[2] for i in its) == pytest.approx(e)
        assert min(i.bbox[1] for i in its) == pytest.approx(s) and max(i.bbox[3] for i in its) == pytest.approx(n)
        start, end = c.extent.temporal.intervals[0]
        assert start == min(pystac.utils.str_to_datetime(i.properties["start_datetime"]) for i in its)
        assert end == max(pystac.utils.str_to_datetime(i.properties["end_datetime"]) for i in its)
        assert start < end


def test_items_geometry_bbox_and_dates(catalog):
    for c, i in items(catalog):
        g = shape(i.geometry)
        assert g.is_valid, i.id
        assert -180 <= i.bbox[0] < i.bbox[2] <= 180 and -90 <= i.bbox[1] < i.bbox[3] <= 90
        assert box(*i.bbox).buffer(1e-6).contains(g), f"{c.id}/{i.id}: geometry outside bbox"
        assert i.datetime is None
        if "license" in i.properties:  # an item with its own licence links to it
            assert any(lk.rel == "license" for lk in i.links), i.id
        assert i.properties["start_datetime"] < i.properties["end_datetime"]
        assert any(lk.rel == "via" and "github.com/oloyededavid/" in lk.href for lk in i.links)


def test_assets_exist_with_matching_size_and_checksum(catalog):
    for c, i in items(catalog):
        for key, a in i.assets.items():
            if a.href.startswith("http"):
                continue  # linked, not copied (file larger than the limit)
            p = Path(a.get_absolute_href())
            assert p.exists(), p
            assert a.extra_fields["file:size"] == p.stat().st_size, p
            assert a.extra_fields["file:checksum"] == multihash_sha256(p), p


def test_file_and_site_size_limits(stats):
    defaults, _ = load_sources()
    for p in DOCS.rglob("*"):
        if p.is_file():
            assert p.stat().st_size < defaults["max_file_mb"] * MB, p
    assert sum(p.stat().st_size for p in DOCS.rglob("*") if p.is_file()) < defaults["max_docs_mb"] * MB


def test_vector_assets_geoparquet_and_geojson_agree(catalog):
    n = 0
    for c, i in items(catalog):
        if i.properties["geocat:kind"] != "vector":
            continue
        n += 1
        pqp = Path(i.assets["geoparquet"].get_absolute_href())
        meta = json.loads(pq.read_schema(pqp).metadata[b"geo"])
        assert meta["version"].startswith("1."), meta["version"]
        g1 = gpd.read_parquet(pqp)
        g2 = gpd.read_file(i.assets["geojson"].get_absolute_href())
        assert g1.crs.to_epsg() == 4326
        assert len(g1) == len(g2) == i.properties["table:row_count"] > 0
        assert [col["name"] for col in i.properties["table:columns"]] == list(g1.columns)
        assert g1.geometry.is_valid.all()
        assert g1.total_bounds == pytest.approx(i.bbox)
    assert n > 0


def test_raster_assets_are_valid_cogs(catalog):
    n = 0
    for c, i in items(catalog):
        if i.properties["geocat:kind"] != "raster":
            continue
        n += 1
        a = i.assets["cog"]
        assert "cloud-optimized" in a.media_type
        p = a.get_absolute_href()
        valid, errors, _ = cog_validate(p, quiet=True)
        assert valid, (p, errors)
        with rasterio.open(p) as s:
            assert f"EPSG:{s.crs.to_epsg()}" == i.properties["proj:code"]
            assert [s.height, s.width] == i.properties["proj:shape"]
        assert "overview" in i.assets["preview"].roles
    assert n > 0


def test_every_configured_source_is_built_or_pending(catalog, stats):
    _, sources = load_sources()
    built = {c.id for c in catalog.get_collections()}
    pending = {p["id"] for p in stats["pending"]}
    assert built | pending == {s["id"] for s in sources}
    assert not built & pending


def test_stats_match_catalogue(catalog, stats):
    its = items(catalog)
    assert stats["n_collections"] == len(list(catalog.get_collections()))
    assert stats["n_items"] == len(its)
    assert stats["n_vector_items"] == sum(i.properties["geocat:kind"] == "vector" for _, i in its)
    assert stats["n_raster_items"] == sum(i.properties["geocat:kind"] == "raster" for _, i in its)
    assert stats["n_features"] == sum(i.properties.get("table:row_count", 0) for _, i in its)
    local = [Path(a.get_absolute_href()) for _, i in its for a in i.assets.values() if not a.href.startswith("http")]
    assert stats["n_data_files"] == len(local)
    assert stats["bytes_data_files"] == sum(p.stat().st_size for p in local)
    index = json.loads((DOCS / "data" / "search_index.json").read_text())
    assert len(index) == len(its)
    assert all((DOCS / e["page"]).exists() for e in index), "item page missing; run scripts/build_site.py"
