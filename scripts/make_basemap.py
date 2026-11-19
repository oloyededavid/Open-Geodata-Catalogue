"""Write docs/assets/basemap.geojson: African country outlines for the website's maps, from Natural Earth
1:50m admin 0 countries (public domain), simplified to about 2 km and rounded to 0.001 degree.

    curl -LO https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip
    python scripts/make_basemap.py ne_50m_admin_0_countries.zip
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DOCS  # noqa: E402


def main(src):
    g = gpd.read_file(src)
    g = g[g["CONTINENT"] == "Africa"][["NAME", "geometry"]].rename(columns={"NAME": "name"}).to_crs(4326)
    g["geometry"] = shapely.set_precision(g.geometry.simplify(0.02, preserve_topology=True).values, 0.001)
    g = g[~g.geometry.is_empty]
    out = json.loads(g.to_json(drop_id=True))
    out["source"] = "Natural Earth 1:50m admin 0 countries (public domain), Africa, simplified"
    (DOCS / "assets" / "basemap.geojson").write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {len(g)} outlines")


if __name__ == "__main__":
    main(sys.argv[1])
