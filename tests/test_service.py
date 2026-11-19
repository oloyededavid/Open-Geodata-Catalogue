"""OGC API Features service: load the catalogue into PostGIS, start pygeoapi (Flask test client) and query it.

Uses the database in OGC_TEST_DSN when set (the GitHub Actions workflow sets it to a PostGIS service
container). Otherwise starts a temporary PostgreSQL 16 + PostGIS cluster with scripts/pgtemp.py and removes it
afterwards; the tests are skipped when the PostgreSQL binaries are not installed.
"""
import os
from pathlib import Path

import psycopg2
import pytest
import yaml

import build_service_config
import service_check
from common import table_name, vector_items
from load_postgis import load
from pgtemp import PG_BIN, TempPostGIS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dsn():
    if os.environ.get("OGC_TEST_DSN"):
        yield os.environ["OGC_TEST_DSN"]
        return
    if not (PG_BIN / "initdb").exists():
        pytest.skip("PostgreSQL binaries not found; set OGC_TEST_DSN or PG_BIN")
    with TempPostGIS() as d:
        yield d


@pytest.fixture(scope="module")
def tables(dsn):
    return load(dsn, quiet=True)


@pytest.fixture(scope="module")
def client(dsn, tables):
    return service_check.flask_client(dsn)


def test_config_is_up_to_date():
    on_disk = yaml.safe_load((ROOT / "service" / "pygeoapi-config.yml").read_text())
    assert on_disk == build_service_config.build(), "rerun scripts/build_service_config.py"


def test_every_vector_item_loaded_with_srid_and_index(dsn, tables):
    expected = {table_name(c.id, i.id): i.properties["table:row_count"] for c, i, _ in vector_items()}
    assert {t["table"]: t["rows"] for t in tables} == expected
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        for t in expected:
            cur.execute("SELECT srid FROM geometry_columns WHERE f_table_name = %s AND f_geometry_column = 'geom'", (t,))
            assert cur.fetchone()[0] == 4326
            cur.execute("SELECT count(*) FROM pg_indexes WHERE tablename = %s AND indexdef ILIKE '%%USING gist (geom)%%'", (t,))
            assert cur.fetchone()[0] == 1
            cur.execute(f'SELECT count(*), bool_and(ST_IsValid(geom)), count(DISTINCT fid) FROM "{t}"')
            n, valid, ids = cur.fetchone()
            assert n == ids == expected[t] and valid


def test_conformance(client):
    conf = client.get("/conformance?f=json").get_json()["conformsTo"]
    for c in service_check.CONFORMANCE_REQUIRED:
        assert c in conf


def test_collections_list_matches_catalogue(client, tables):
    r = client.get("/collections?f=json")
    assert r.status_code == 200
    ids = {c["id"] for c in r.get_json()["collections"]}
    assert ids == {t["table"] for t in tables}


def test_items_limit_and_paging(client, tables):
    t = max(tables, key=lambda x: x["rows"])
    page = client.get(f"/collections/{t['table']}/items?f=json&limit=5").get_json()
    assert len(page["features"]) == 5 and page["numberMatched"] == t["rows"] and page["numberReturned"] == 5
    assert any(lk["rel"] == "next" for lk in page["links"])
    nxt = client.get(f"/collections/{t['table']}/items?f=json&limit=5&offset=5").get_json()
    assert {f["id"] for f in page["features"]}.isdisjoint({f["id"] for f in nxt["features"]})


def test_bbox_filter(client, tables):
    t = next(x for x in tables if x["table"].endswith("storage_trend_cells"))
    # 1-degree cells centred on half degrees: this box lies inside the single cell centred at 14.5 E, 13.5 N
    r = client.get(f"/collections/{t['table']}/items?f=json&bbox=14.2,13.2,14.8,13.8").get_json()
    assert r["numberMatched"] == 1
    p = r["features"][0]["properties"]
    assert (p["cell_lon"], p["cell_lat"]) == (14.5, 13.5)
    far = client.get(f"/collections/{t['table']}/items?f=json&bbox=-150,-40,-149,-39").get_json()
    assert far["numberMatched"] == 0


def test_full_service_check(client, tables):
    res = service_check.run_checks(client, tables)
    assert res["n_collections"] == len(tables)
