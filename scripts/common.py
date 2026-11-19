"""Paths and small helpers shared by the build, load and check scripts."""
import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STAC = DOCS / "stac"
DATA = DOCS / "data"
SOURCES = ROOT / "catalogue" / "sources.yaml"
SERVICE = ROOT / "service"
SITE_URL = "https://oloyededavid.github.io/Open-Geodata-Catalogue/"
REPO_URL = "https://github.com/oloyededavid/Open-Geodata-Catalogue"


def load_sources(path=SOURCES):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = cfg.get("defaults", {})
    return defaults, cfg["sources"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def multihash_sha256(path):
    """file:checksum value of the STAC file extension: multihash code 0x12 (sha2-256), length 0x20, digest."""
    return "1220" + sha256(path)


def table_name(collection_id, item_id):
    """PostgreSQL table (and OGC API collection id) for a vector item. Lower case, underscores, at most 63 chars."""
    name = re.sub(r"[^a-z0-9]+", "_", f"{collection_id}__{item_id}".lower()).strip("_")
    if len(name) > 63:
        name = name[:54] + "_" + hashlib.sha1(name.encode()).hexdigest()[:8]
    return name


def vector_items(catalog_path=STAC / "catalog.json"):
    """(collection, item, geoparquet path) for every vector item in the built catalogue."""
    import pystac
    cat = pystac.Catalog.from_file(str(catalog_path))
    out = []
    for col in cat.get_collections():
        for item in col.get_items():
            a = item.assets.get("geoparquet")
            if a is None:
                continue
            out.append((col, item, Path(a.get_absolute_href())))
    return out


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
