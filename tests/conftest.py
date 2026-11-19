import json
import sys
from pathlib import Path

import pystac
import pytest
from pystac.validation import JsonSchemaSTACValidator, set_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMAS = {  # extension schemas kept in tests/schemas so validation works offline
    "https://stac-extensions.github.io/file/v2.1.0/schema.json": "file-v2.1.0.json",
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json": "projection-v2.0.0.json",
    "https://stac-extensions.github.io/table/v1.2.0/schema.json": "table-v1.2.0.json",
    "https://proj.org/schemas/v0.7/projjson.schema.json": "projjson-v0.7.json",
}


@pytest.fixture(scope="session")
def validator():
    v = JsonSchemaSTACValidator()
    for uri, f in SCHEMAS.items():
        v.schema_cache[uri] = json.loads((ROOT / "tests" / "schemas" / f).read_text())
    set_validator(v)
    return v


@pytest.fixture(scope="session")
def catalog(validator):
    return pystac.Catalog.from_file(str(ROOT / "docs" / "stac" / "catalog.json"))


@pytest.fixture(scope="session")
def stats():
    return json.loads((ROOT / "docs" / "data" / "catalogue_stats.json").read_text())
