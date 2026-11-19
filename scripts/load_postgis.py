"""Load every vector layer of the STAC catalogue into PostGIS, one table per item.

Reads the GeoParquet asset of each vector item in docs/stac, creates a table named <collection>_<item>
(see common.table_name) with an integer primary key `fid`, the layer's attributes and a `geom` column of
type geometry(Geometry, 4326), adds a GiST index on `geom` and runs ANALYZE. A table `geocat_layers` lists
what was loaded. Existing tables of the same name are replaced.

    python scripts/load_postgis.py --dsn postgresql://postgres:postgres@localhost:5432/geodata
    (or set DATABASE_URL)
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import STAC, table_name, vector_items  # noqa: E402

SRID = 4326


def pg_type(series):
    k = series.dtype.kind
    if k == "b":
        return "boolean"
    if k in "iu":
        return "bigint"
    if k == "f":
        return "double precision"
    if k == "M":
        return "timestamptz"
    return "text"


def py_value(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def load_table(cur, gdf, table, title):
    gdf = gdf.to_crs(SRID) if gdf.crs and gdf.crs.to_epsg() != SRID else gdf
    cols = [c for c in gdf.columns if c != gdf.geometry.name]
    clash = {"fid", "geom"} & {c.lower() for c in cols}
    if clash:
        raise ValueError(f"{table}: attribute names {clash} clash with the key or geometry column")
    t = sql.Identifier(table)
    cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(t))
    defs = [sql.SQL("fid integer PRIMARY KEY")]
    defs += [sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(pg_type(gdf[c]))) for c in cols]
    defs += [sql.SQL("geom geometry(Geometry, {}) NOT NULL").format(sql.Literal(SRID))]
    cur.execute(sql.SQL("CREATE TABLE {} ({})").format(t, sql.SQL(", ").join(defs)))
    values = gdf[cols].astype(object).to_numpy() if cols else [[]] * len(gdf)
    rows = [[i] + [py_value(v) for v in vals] + [psycopg2.Binary(g.wkb)]
            for i, (vals, g) in enumerate(zip(values, gdf.geometry), start=1)]
    names = sql.SQL(", ").join([sql.Identifier("fid")] + [sql.Identifier(c) for c in cols] + [sql.Identifier("geom")])
    template = "(" + ", ".join(["%s"] * (len(cols) + 1)) + f", ST_SetSRID(ST_GeomFromWKB(%s), {SRID}))"
    execute_values(cur, sql.SQL("INSERT INTO {} ({}) VALUES %s").format(t, names).as_string(cur), rows,
                   template=template, page_size=500)
    cur.execute(sql.SQL("CREATE INDEX {} ON {} USING GIST (geom)").format(sql.Identifier(f"{table[:50]}_geom_gix"), t))
    cur.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(t, sql.Literal(title)))
    cur.execute(sql.SQL("ANALYZE {}").format(t))
    return len(rows)


def load(dsn, catalog_path=STAC / "catalog.json", quiet=False):
    """Load all vector items; returns a list of dicts describing each table."""
    out = []
    conn = psycopg2.connect(dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cur.execute("DROP TABLE IF EXISTS geocat_layers")
            cur.execute("CREATE TABLE geocat_layers (table_name text PRIMARY KEY, collection text, item text, "
                        "title text, rows integer, srid integer, bbox double precision[])")
            for col, item, parquet in vector_items(catalog_path):
                gdf = gpd.read_parquet(parquet)
                table = table_name(col.id, item.id)
                n = load_table(cur, gdf, table, item.properties.get("title", item.id))
                cur.execute(sql.SQL("SELECT Find_SRID('public', {}, 'geom'), ST_Extent(geom)::box2d::text FROM {}").format(
                    sql.Literal(table), sql.Identifier(table)))
                srid, _ = cur.fetchone()
                cur.execute("INSERT INTO geocat_layers VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (table, col.id, item.id, item.properties.get("title"), n, srid, list(item.bbox)))
                out.append({"table": table, "collection": col.id, "item": item.id, "rows": n, "srid": srid})
                if not quiet:
                    print(f"{table}: {n} rows, SRID {srid}")
    finally:
        conn.close()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/geodata"))
    ap.add_argument("--catalog", default=str(STAC / "catalog.json"))
    a = ap.parse_args()
    tables = load(a.dsn, Path(a.catalog))
    print(f"loaded {len(tables)} tables, {sum(t['rows'] for t in tables)} features")


if __name__ == "__main__":
    main()
