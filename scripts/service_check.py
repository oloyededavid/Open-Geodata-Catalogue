"""Start the OGC API Features service in-process against a PostGIS database and check it.

Used by tests/test_service.py and by `python scripts/service_check.py`, which starts a temporary PostGIS
(scripts/pgtemp.py) unless DATABASE_URL is set, loads the catalogue, runs the checks with pygeoapi's Flask
test client and writes docs/data/service_check.json. The numbers on the website about the service come
from that file.
"""
import atexit
import datetime as dt
import shutil
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, SERVICE  # noqa: E402

CONFORMANCE_REQUIRED = [
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
]


def set_db_env(dsn):
    u = urlparse(dsn)
    os.environ.update({"POSTGRES_HOST": u.hostname or "localhost", "POSTGRES_PORT": str(u.port or 5432),
                       "POSTGRES_DB": u.path.lstrip("/") or "geodata", "POSTGRES_USER": u.username or "postgres",
                       "POSTGRES_PASSWORD": u.password or ""})


def flask_client(dsn, config=SERVICE / "pygeoapi-config.yml"):
    """pygeoapi's Flask app configured from service/pygeoapi-config.yml, pointed at `dsn`."""
    set_db_env(dsn)
    os.environ["PYGEOAPI_CONFIG"] = str(config)
    os.environ.setdefault("PYGEOAPI_SERVER_URL", "http://localhost:5000")
    from pygeoapi.openapi import generate_openapi_document
    with open(config, encoding="utf-8") as fh:
        doc = generate_openapi_document(fh, "yaml")
    tmp = tempfile.mkdtemp(prefix="geocat-oas-")
    atexit.register(shutil.rmtree, tmp, True)
    oas = Path(tmp) / "openapi.yml"
    oas.write_text(doc, encoding="utf-8")
    os.environ["PYGEOAPI_OPENAPI"] = str(oas)
    if "pygeoapi.flask_app" in sys.modules:
        app_mod = importlib.reload(sys.modules["pygeoapi.flask_app"])
    else:
        app_mod = importlib.import_module("pygeoapi.flask_app")
    return app_mod.APP.test_client()


def get(client, path):
    r = client.get(path, headers={"Accept": "application/json"})
    assert r.status_code == 200, (path, r.status_code, r.data[:300])
    return r.get_json()


def run_checks(client, tables):
    """Check landing page, conformance, collections, items paging, single features and bbox filtering.
    `tables` is the list returned by load_postgis.load(). Returns a summary dict; raises AssertionError on failure."""
    from shapely.geometry import box, shape
    landing = get(client, "/")
    conf = get(client, "/conformance")["conformsTo"]
    missing = [c for c in CONFORMANCE_REQUIRED if c not in conf]
    assert not missing, missing
    cols = get(client, "/collections")["collections"]
    ids = {c["id"] for c in cols}
    assert ids == {t["table"] for t in tables}, (ids, [t["table"] for t in tables])
    per = []
    for t in tables:
        cid = t["table"]
        meta = get(client, f"/collections/{cid}")
        page = get(client, f"/collections/{cid}/items?limit=1")
        assert page["type"] == "FeatureCollection" and len(page["features"]) == 1
        assert page["numberMatched"] == t["rows"], (cid, page["numberMatched"], t["rows"])
        everything = {"features": []}
        while len(everything["features"]) < t["rows"]:  # page through: the server returns at most 1000 at a time
            pg = get(client, f"/collections/{cid}/items?limit=1000&offset={len(everything['features'])}")
            assert pg["features"], (cid, len(everything["features"]))
            everything["features"] += pg["features"]
        assert len(everything["features"]) == t["rows"]
        assert len({f["id"] for f in everything["features"]}) == t["rows"], f"{cid}: paging repeated features"
        # every returned geometry lies inside the extent the collection advertises (catches swapped axes)
        ext = box(*meta["extent"]["spatial"]["bbox"][0]).buffer(1e-6)
        assert all(ext.contains(shape(f["geometry"])) for f in everything["features"]), f"{cid}: outside extent"
        f0 = everything["features"][0]
        one = get(client, f"/collections/{cid}/items/{f0['id']}")
        assert one["id"] == f0["id"]
        # bbox: a small box around a point on the first feature must return exactly the features that
        # intersect it (computed here with shapely from the full download); a box in the South Pacific none
        p = shape(f0["geometry"]).representative_point()
        bb = (p.x - 0.01, p.y - 0.01, p.x + 0.01, p.y + 0.01)
        expect = {f["id"] for f in everything["features"] if shape(f["geometry"]).intersects(box(*bb))}
        got = get(client, f"/collections/{cid}/items?limit=1000&bbox={','.join(f'{v:.6f}' for v in bb)}")
        assert {f["id"] for f in got["features"]} == expect and f0["id"] in expect, cid
        none = get(client, f"/collections/{cid}/items?bbox=-150,-40,-149,-39")
        assert none["numberMatched"] == 0 and not none["features"]
        per.append({"collection": cid, "title": meta["title"], "features": t["rows"],
                    "bbox_test_matched": len(expect)})
    return {"landing_title": landing.get("title"), "conformance_classes": len(conf),
            "conformance": sorted(conf), "n_collections": len(cols), "collections": per,
            "n_features": sum(t["rows"] for t in tables)}


def main():
    import pygeoapi
    import psycopg2
    from load_postgis import load
    from pgtemp import TempPostGIS

    def run(dsn):
        tables = load(dsn, quiet=True)
        res = run_checks(flask_client(dsn), tables)
        with psycopg2.connect(dsn) as c, c.cursor() as cur:
            cur.execute("SELECT postgis_lib_version(), current_setting('server_version')")
            res["postgis_version"], res["postgresql_version"] = cur.fetchone()
        return res

    if os.environ.get("DATABASE_URL"):
        res = run(os.environ["DATABASE_URL"])
    else:
        with TempPostGIS() as dsn:
            res = run(dsn)
    res.update({"checked": dt.date.today().isoformat(), "pygeoapi_version": pygeoapi.__version__})
    (DATA / "service_check.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(f"service check passed: {res['n_collections']} collections, {res['n_features']} features, "
          f"{res['conformance_classes']} conformance classes")


if __name__ == "__main__":
    main()
