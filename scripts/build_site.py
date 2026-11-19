"""Build the static website in docs/ from the STAC catalogue and the generated JSON files.

Writes docs/index.html, docs/collections/<collection>.html, docs/items/<collection>/<item>.html,
docs/data/footprints.geojson and docs/assets/basemap.geojson. Every count, size and date on the pages is read
from docs/data/catalogue_stats.json, docs/data/service_check.json or the STAC JSON files; numbers taken from
the stats files are wrapped in <span data-stat="..."> so tests/test_site.py can check them.

    python scripts/build_site.py
"""
import html
import json
import sys
from pathlib import Path

import pystac

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DOCS, REPO_URL, SITE_URL, STAC, read_json, table_name  # noqa: E402

E = html.escape
FONTS = """    <link rel="preconnect" href="https://api.fontshare.com">
    <link rel="preconnect" href="https://cdn.fontshare.com" crossorigin>
    <link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&amp;display=swap">
    <link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=zodiak@500,700&amp;display=swap">"""
ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' "
        "height='32' rx='6' fill='%23111'/%3E%3Ccircle cx='16' cy='16' r='6' fill='%231f5fae'/%3E%3C/svg%3E")
FORMAT = {"geoparquet": "GeoParquet", "geojson": "GeoJSON", "cog": "Cloud-Optimised GeoTIFF", "preview": "PNG quick-look"}


# ---------------------------------------------------------------- formatting
def n(x):
    return f"{x:,}"


def mb(b):
    return f"{b / 1e6:.1f}"


def size(b):
    return f"{b / 1e6:.1f} MB" if b >= 1_000_000 else f"{b / 1e3:.0f} KB" if b >= 1000 else f"{b} bytes"


def years(start, end):
    a, b = start[:4], end[:4]
    return a if a == b else f"{a}–{b}"


def stat(key, text):
    return f'<span data-stat="{E(key)}">{E(str(text))}</span>'


def licence_text(lic):
    return {"CC-BY-4.0": "CC BY 4.0", "MIT": "MIT", "ODbL-1.0": "ODbL 1.0", "other": "not stated separately", "various": "various, see note"}.get(lic, lic)


# ---------------------------------------------------------------- page shell
def includes():
    a = DOCS / "assets"
    return {k: (a / f"{k}.html").read_text(encoding="utf-8").strip() for k in ("study-bar", "study-nav", "study-others")}


def page(*, title, description, body, base, path, toc, scripts=("leaflet",), end_nav=False):
    inc = includes()
    toc_html = "\n".join(f'            <a href="{h}">{E(t)}</a>' for h, t in toc)
    toc_phone = "\n".join(f'        <a href="{h}">{E(t)}</a>' for h, t in toc)
    leaflet_css = f'    <link rel="stylesheet" href="{base}vendor/leaflet-1.9.4/leaflet.css">\n' if "leaflet" in scripts else ""
    js = ""
    if "leaflet" in scripts:
        js += f'<script src="{base}vendor/leaflet-1.9.4/leaflet.js"></script>\n<script src="{base}assets/catalogue.js"></script>\n'
    js += f'<script src="{base}assets/study.js"></script>'
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="only light">
    <title>{E(title)}</title>
    <link rel="canonical" href="{SITE_URL}{path}">
    <meta property="og:type" content="website">
    <meta property="og:title" content="{E(title)}">
    <meta property="og:description" content="{E(description)}">
    <meta property="og:url" content="{SITE_URL}{path}">
    <meta name="description" content="{E(description)}">
    <meta name="author" content="David Oloyede">
    <link rel="icon" href="{ICON}">
{FONTS}
{leaflet_css}    <link rel="stylesheet" href="{base}assets/style.css">
    <link rel="stylesheet" href="{base}assets/catalogue.css">
</head>
<body data-base="{base}">
{inc['study-bar']}
<nav class="skipnav" aria-label="Skip link"><a class="skip" href="#main">Skip to the content</a></nav>
<header class="site-header">
    <div class="site-inner">
        <a class="site-id" href="{base}index.html">Open geodata catalogue</a>
        <nav class="toc" aria-label="Sections">
{toc_html}
        </nav>
    </div>
    <nav class="toc-phone" aria-label="Sections on phone">
{toc_phone}
    </nav>
    <div class="progress" aria-hidden="true"><span id="progress"></span></div>
</header>

<main class="article" id="main">
{body}
</main>

<button type="button" class="to-top" id="to-top" aria-label="Back to top" hidden><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button>
{inc['study-nav'] if end_nav else ''}
<footer>
    <div class="inner">
        <p class="sig"><span>David Oloyede</span><span><a href="https://github.com/oloyededavid">github.com/oloyededavid</a></span><span><a href="{REPO_URL}">Repository</a></span></p>
        <p>Catalogue code MIT. Each collection keeps the data licence its study states (mostly CC BY 4.0); the source datasets behind the studies keep their own terms. Map outlines: Natural Earth (public domain).</p>
        {inc['study-others']}
    </div>
</footer>
{js}
</body>
</html>
"""


# ---------------------------------------------------------------- data files for the pages
def write_basemap():
    """The outlines are made once by scripts/make_basemap.py from Natural Earth; here only checked."""
    if not (DOCS / "assets" / "basemap.geojson").exists():
        raise SystemExit("docs/assets/basemap.geojson missing: run scripts/make_basemap.py")


def write_footprints(cat):
    feats = []
    for c in cat.get_collections():
        for i in c.get_items():
            feats.append({"type": "Feature", "geometry": i.geometry,
                          "properties": {"collection": c.id, "id": i.id, "title": i.properties["title"],
                                         "kind": i.properties["geocat:kind"]}})
    (DATA / "footprints.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                        separators=(",", ":")) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- index
def index_page(cat, S, svc):
    cards = []
    for c in S["collections"]:
        cid = c["id"]
        k = f"c:{cid}"
        kinds = []
        if c["vector"]:
            kinds.append(f'{stat(k + ":vector", c["vector"])} vector')
        if c["raster"]:
            kinds.append(f'{stat(k + ":raster", c["raster"])} raster')
        coll = cat.get_child(cid)
        cards.append(f"""<li class="cat-card">
    <div class="cat-thumb" data-thumb="{cid}" data-bbox="{E(json.dumps(c['bbox']))}" aria-hidden="true"></div>
    <div class="cat-card-body">
        <h3><a href="collections/{cid}.html">{E(c['title'])}</a></h3>
        <p class="cat-desc">{E(coll.description)}</p>
        <p class="cat-meta-line"><span>{stat(k + ':items', c['items'])} item{'s' if c['items'] != 1 else ''}: {', '.join(kinds)}</span><span>{stat(k + ':years', years(c['start'], c['end']))}</span><span>Data {E(licence_text(c['licence_data']))}</span></p>
        <p class="cat-links"><a href="{E(c['page'])}">Study page</a><a href="{E(c['github'])}">Repository</a><a href="stac/{cid}/collection.json">STAC collection</a></p>
    </div>
</li>""")
    pending = ""
    if S["pending"]:
        rows = "; ".join(f'<a href="https://github.com/oloyededavid/{E(p["repo"])}">{E(p["repo"])}</a> ({E(p["reason"])})' for p in S["pending"])
        one = S["n_pending"] == 1
        pending = (f'<p class="cat-pending">Listed in <code>catalogue/sources.yaml</code> but not added at the last build '
                   f'({stat("n_pending", S["n_pending"])} {"study" if one else "studies"}): {rows}. '
                   f'{"It is" if one else "Each is"} added by rebuilding once its repository has outputs, a study period '
                   f'and a licence statement.</p>')
    options = "\n".join(f'<option value="{c["id"]}">{E(c["title"])}</option>' for c in S["collections"])
    svc_html = ""
    if svc:
        svc_html = (f'<p>At the last local check ({stat("svc:checked", svc["checked"])}), the service served '
                    f'{stat("svc:n_collections", svc["n_collections"])} collections with '
                    f'{stat("svc:n_features", n(svc["n_features"]))} features from PostGIS '
                    f'{stat("svc:postgis_version", svc["postgis_version"])} with pygeoapi '
                    f'{stat("svc:pygeoapi_version", svc["pygeoapi_version"])}, and every check passed: paging with '
                    f'<code>limit</code>, single features, bounding-box filtering and the core, GeoJSON and OpenAPI '
                    f'conformance classes. pygeoapi declares {stat("svc:conformance_classes", svc["conformance_classes"])} '
                    f'conformance classes in all; the others were not tested here, and no formal OGC test suite was run.</p>')
    first = S["collections"][0]["id"]
    body = f"""<header class="title">
    <h1>Open geodata catalogue</h1>
    <p class="subtitle">Spatial outputs of {stat('n_collections', S['n_collections'])} open studies by David Oloyede, as a static STAC catalogue and as an OGC API Features service you can run yourself.</p>
    <p class="sig"><span>David Oloyede</span><span>Built {stat('built', S['built'])}</span></p>
</header>

<section id="overview" aria-labelledby="h-overview">
    <h2 class="sr-only" id="h-overview">Overview</h2>
    <p class="cat-intro">Each study publishes its maps and tables on its own page. This catalogue lists the spatial layers behind them in one place, in open formats with checksums, so they can be found, downloaded and loaded into GIS software or code without reading each repository. The layers are the studies' own outputs and keep their limits; the study pages explain what each one can and cannot show.</p>
    <dl class="cat-figures">
        <div><dt>Collections</dt><dd>{stat('n_collections', S['n_collections'])}</dd></div>
        <div><dt>Items</dt><dd>{stat('n_items', S['n_items'])}</dd></div>
        <div><dt>Data files</dt><dd>{stat('n_data_files', S['n_data_files'])}</dd></div>
        <div><dt>Size</dt><dd>{stat('mb_data_files', mb(S['bytes_data_files']))}&nbsp;<small>MB</small></dd></div>
        <div><dt>Vector features</dt><dd>{stat('n_features', n(S['n_features']))}</dd></div>
    </dl>
</section>

<section id="collections" aria-labelledby="h-collections" class="wide">
    <h2 class="cat-h" id="h-collections">Collections</h2>
    <p class="cat-lead">One collection per study. The small maps show each collection's extent (dashed) and its items, on country outlines.</p>
    <ul class="cat-cards" role="list">
{chr(10).join(cards)}
    </ul>
    {pending}
</section>

<section id="search" aria-labelledby="h-search">
    <h2 class="cat-h" id="h-search">Search the items</h2>
    <p class="cat-lead">Filter the {stat('n_items', S['n_items'])} items by words in their title, description or keywords, by type and by study. The search runs in your browser.</p>
    <div class="cat-search" role="search">
        <label for="q">Search words</label><input id="q" type="search" placeholder="for example: rainfall, Lagos, 2020" autocomplete="off">
        <label for="kind">Type</label><select id="kind"><option value="">All types</option><option value="vector">Vector</option><option value="raster">Raster</option></select>
        <label for="coll">Study</label><select id="coll"><option value="">All studies</option>
{options}
        </select>
    </div>
    <p id="search-status" class="cat-status" role="status">Turn on JavaScript to search; every item is also listed on its collection page.</p>
    <ul id="results" class="cat-results"></ul>
</section>

<section id="use" aria-labelledby="h-use">
    <h2 class="cat-h" id="h-use">Use the data</h2>
    <p>The catalogue root is <a href="stac/catalog.json"><code>stac/catalog.json</code></a>. All links inside it are relative, so it can be copied or mirrored as a folder. Vector layers come as GeoParquet and GeoJSON in longitude–latitude (EPSG:4326); rasters as Cloud-Optimised GeoTIFFs in their original grid, with a PNG quick-look. Each file has its size and SHA-256 checksum in the STAC item (<code>file:size</code>, <code>file:checksum</code>).</p>
    <pre class="cat-code" tabindex="0"><code>import pystac, geopandas as gpd
cat = pystac.Catalog.from_file("{SITE_URL}stac/catalog.json")
item = cat.get_child("{first}").get_item("study-areas")
gdf = gpd.read_parquet(item.assets["geoparquet"].get_absolute_href())</code></pre>
    <p>A Cloud-Optimised GeoTIFF can be read over HTTP without downloading it first, for example in QGIS (Add Raster Layer, protocol HTTP) or with GDAL: <code>gdalinfo /vsicurl/{SITE_URL}stac/…/item.tif</code>.</p>
</section>

<section id="api" aria-labelledby="h-api">
    <h2 class="cat-h" id="h-api">OGC API Features</h2>
    <p>The {stat('n_vector_items', S['n_vector_items'])} vector layers can also be served as OGC API Features collections from PostGIS with pygeoapi, so that GIS clients can query them by bounding box and page through features. This website is static and cannot run that service. To run it, clone the repository and start it with Docker Compose, or locally with PostgreSQL, PostGIS and pygeoapi installed (see the README):</p>
    <pre class="cat-code" tabindex="0"><code>docker compose up
curl "http://localhost:5000/collections"
curl "http://localhost:5000/collections/{table_name(first, 'study-areas')}/items?limit=5&amp;bbox=3,5,10,17"</code></pre>
    {svc_html}
    <p>How the catalogue and the service are built, and what was and was not checked, is described on the <a href="about.html">design page</a>.</p>
</section>

<section id="limits" aria-labelledby="h-limits">
    <h2 class="cat-h" id="h-limits">Limits</h2>
    <ul>
        <li>The layers are copies of the studies' outputs at the commits recorded in each collection. If a study changes, the catalogue is out of date until it is rebuilt.</li>
        <li>Most layers are satellite or model estimates (rainfall, evapotranspiration, gravity, land surface temperature), not ground measurements. Their uncertainty and validation are described in the studies, not here.</li>
        <li>Only outputs already stored in the study repositories are included. Large intermediate rasters that the studies rebuild from public archives are not.</li>
    </ul>
</section>"""
    toc = [("#collections", "Collections"), ("#search", "Search"), ("#use", "Use the data"), ("#api", "API"), ("about.html", "Design")]
    return page(title="Open geodata catalogue", base="", path="", toc=toc, end_nav=True,
                description=f"Spatial outputs of {S['n_collections']} open studies as a static STAC catalogue, with an OGC API Features service.",
                body=body)


# ---------------------------------------------------------------- collection and item pages
def asset_rows(item, base_href):
    rows = []
    for key, a in item.assets.items():
        fs, ck = a.extra_fields.get("file:size"), a.extra_fields.get("file:checksum", "")
        href = a.href if a.href.startswith("http") else base_href + a.href.lstrip("./")
        rows.append(f'<tr><th scope="row">{E(FORMAT.get(key, key))}</th><td>{E(a.media_type or "")}</td>'
                    f'<td>{E(size(fs)) if fs else ""}</td><td><code title="{E(ck)}">{E(ck[4:16])}…</code></td>'
                    f'<td><a href="{E(href)}" download>Download</a></td></tr>')
    return ("<div class=\"cat-table\"><table><thead><tr><th scope=\"col\">File</th><th scope=\"col\">Media type</th>"
            "<th scope=\"col\">Size</th><th scope=\"col\">SHA-256 (start)</th><th scope=\"col\"></th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def collection_page(coll, cstat):
    items = list(coll.get_items())
    trs = []
    for i in items:
        p = i.properties
        detail = (f'{n(p["table:row_count"])} features' if p["geocat:kind"] == "vector"
                  else f'{p["proj:shape"][1]} × {p["proj:shape"][0]} cells')
        total = sum(a.extra_fields.get("file:size", 0) for a in i.assets.values() if not a.href.startswith("http"))
        trs.append(f'<tr><th scope="row"><a href="../items/{coll.id}/{i.id}.html">{E(p["title"])}</a></th>'
                   f'<td>{E(p["geocat:kind"])}</td><td>{E(years(p["start_datetime"], p["end_datetime"]))}</td>'
                   f'<td>{E(detail)}</td><td>{E(size(total))}</td></tr>')
    about = [lk for lk in coll.links if lk.rel == "about"][0].href
    via = [lk for lk in coll.links if lk.rel == "via"][0].href
    lic_links = " · ".join(f'<a href="{E(lk.href)}">{E(lk.title)}</a>' for lk in coll.links if lk.rel == "license")
    note = coll.extra_fields.get("geocat:licence_note", "")
    t0, t1 = coll.extent.temporal.intervals[0]
    bb = coll.extent.spatial.bboxes[0]
    k = f"c:{coll.id}"
    body = f"""<header class="title">
    <p class="cat-crumbs"><a href="../index.html#collections">Catalogue</a> / Collection</p>
    <h1>{E(coll.title)}</h1>
    <p class="subtitle">{E(coll.description)}</p>
</header>
<section id="map-sec" aria-labelledby="h-map">
    <h2 class="sr-only" id="h-map">Map</h2>
    <div id="collection-map" class="cat-map" data-collection="{coll.id}" role="img" aria-label="Map of the item footprints of this collection"></div>
    <p class="cat-note">Item footprints on country outlines (Natural Earth 1:50m, shown only at small scales because they are too coarse for city scale). Raster footprints are the edges of their grids.</p>
</section>
<section id="details" aria-labelledby="h-details">
    <h2 class="cat-h" id="h-details">About this collection</h2>
    <dl class="cat-dl">
        <dt>Study</dt><dd><a href="{E(about)}">Study page</a> · <a href="{E(via)}">Repository</a></dd>
        <dt>Items</dt><dd>{stat(k + ':items', cstat['items'])}</dd>
        <dt>Period</dt><dd>{E(t0.date().isoformat())} to {E(t1.date().isoformat())}</dd>
        <dt>Extent</dt><dd>{E(', '.join(f'{x:.3f}' for x in bb))} (west, south, east, north; degrees)</dd>
        <dt>Data licence</dt><dd>{E(licence_text(coll.license))}{(' – ' + E(note)) if note else ''} ({lic_links})</dd>
        <dt>Code licence</dt><dd>{E(coll.extra_fields.get('geocat:code_licence', ''))}</dd>
        <dt>Keywords</dt><dd>{E(', '.join(coll.keywords or []))}</dd>
        <dt>Source version</dt><dd>Commit <code>{E(coll.extra_fields['geocat:source_commit'][:7])}</code> of {E(coll.extra_fields['geocat:source_commit_date'])} (branch {E(coll.extra_fields['geocat:source_branch'])})</dd>
        <dt>Metadata</dt><dd><a href="../stac/{coll.id}/collection.json">STAC collection JSON</a></dd>
    </dl>
</section>
<section id="items" aria-labelledby="h-items">
    <h2 class="cat-h" id="h-items">Items</h2>
    <div class="cat-table"><table><thead><tr><th scope="col">Item</th><th scope="col">Type</th><th scope="col">Period</th><th scope="col">Size of data</th><th scope="col">Files</th></tr></thead>
    <tbody>{''.join(trs)}</tbody></table></div>
</section>"""
    toc = [("../index.html#collections", "Catalogue"), ("#details", "About"), ("#items", "Items"), ("../about.html", "Design")]
    return page(title=f"{coll.title} – Open geodata catalogue", base="../", path=f"collections/{coll.id}.html", toc=toc,
                description=coll.description[:300], body=body)


def item_page(coll, item):
    p = item.properties
    base_href = f"../../stac/{coll.id}/{item.id}/"
    kind = p["geocat:kind"]
    via = [lk for lk in item.links if lk.rel == "via"][0]
    rows = [("Collection", f'<a href="../../collections/{coll.id}.html">{E(coll.title)}</a>'),
            ("Period", f'{E(p["start_datetime"][:10])} to {E(p["end_datetime"][:10])}'),
            ("Bounding box", E(", ".join(f"{x:.4f}" for x in item.bbox)) + " (west, south, east, north; degrees)")]
    if kind == "vector":
        cols = [c["name"] for c in p["table:columns"] if c["name"] != "geometry"]
        rows += [("Type", "Vector, longitude–latitude (EPSG:4326)"), ("Features", n(p["table:row_count"])),
                 ("Attributes", E(", ".join(cols)) or "none"),
                 ("OGC API collection", f'<code>{E(table_name(coll.id, item.id))}</code> (when the service is running)')]
        keys = cols[:6]
        mapdiv = (f'<div id="item-map" class="cat-map" data-bbox="{E(json.dumps(item.bbox))}" '
                  f'data-geojson="{base_href}{item.id}.geojson" data-keys="{E(json.dumps(keys))}" role="img" '
                  f'aria-label="Map of the layer"></div><p class="cat-note">Hover over or tap a shape to see its first attributes.</p>')
    else:
        lo, hi = p["geocat:preview_range"]
        nod = "NaN" if p.get("geocat:nodata_is_nan") else p.get("geocat:nodata")
        rows += [("Type", f'Raster, {E(p["proj:code"])}'), ("Grid", f'{p["proj:shape"][1]} × {p["proj:shape"][0]} cells, '
                 f'cell size {abs(p["proj:transform"][0]):g} × {abs(p["proj:transform"][4]):g} (units of the CRS)'),
                 ("Values", E(p.get("geocat:band_description") or "see description")), ("Data type", E(p["geocat:data_type"])),
                 ("No-data value", E(str(nod)))]
        mapdiv = (f'<div id="item-map" class="cat-map" data-bbox="{E(json.dumps(item.bbox))}" '
                  f'data-preview="{base_href}{item.id}.preview.png" data-alt="Quick-look of {E(p["title"])}" role="img" '
                  f'aria-label="Map with a quick-look of the raster"></div>'
                  f'<div class="cat-legend"><span>{lo:.3g}</span><span class="bar" aria-hidden="true"></span><span>{hi:.3g}</span>'
                  f'<span>quick-look colours, 2nd to 98th percentile; download the GeoTIFF for the values</span></div>')
    rows += [("Source", f'<a href="{E(via.href)}">{E(p["geocat:source_file"])}</a> at commit <code>{E(p["geocat:source_commit"][:7])}</code>'),
             ("Metadata", f'<a href="{base_href}{item.id}.json">STAC item JSON</a>')]
    if "license" in p:
        lk = [x for x in item.links if x.rel == "license"]
        rows.insert(3, ("Licence", E(licence_text(p["license"])) + (f' (<a href="{E(lk[0].href)}">text</a>)' if lk else "")
                        + ", which differs from the collection's"))
    dl = "\n".join(f"        <dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    body = f"""<header class="title">
    <p class="cat-crumbs"><a href="../../index.html#collections">Catalogue</a> / <a href="../../collections/{coll.id}.html">Collection</a> / Item</p>
    <h1>{E(p['title'])}</h1>
    <p class="subtitle">{E(p['description'])}</p>
</header>
<section id="map-sec" aria-labelledby="h-map">
    <h2 class="sr-only" id="h-map">Map</h2>
    {mapdiv}
</section>
<section id="details" aria-labelledby="h-details">
    <h2 class="cat-h" id="h-details">Details</h2>
    <dl class="cat-dl">
{dl}
    </dl>
</section>
<section id="files" aria-labelledby="h-files">
    <h2 class="cat-h" id="h-files">Files</h2>
    {asset_rows(item, base_href)}
    <p class="cat-note">Data licence: {E(licence_text(p.get("license", coll.license)))}{" (this item's own licence; see the link in the STAC item)" if "license" in p else ""}. Cite the study when you use these data; the study page explains the methods and limits.</p>
</section>"""
    toc = [("../../index.html#collections", "Catalogue"), (f"../../collections/{coll.id}.html", "Collection"), ("#files", "Files"), ("../../about.html", "Design")]
    return page(title=f"{p['title']} – Open geodata catalogue", base="../../", path=f"items/{coll.id}/{item.id}.html",
                toc=toc, description=p["description"][:300], body=body)


def main():
    S = read_json(DATA / "catalogue_stats.json")
    svc_path = DATA / "service_check.json"
    svc = read_json(svc_path) if svc_path.exists() else None
    cat = pystac.Catalog.from_file(str(STAC / "catalog.json"))
    write_basemap()
    write_footprints(cat)
    for d in ("collections", "items"):
        for f in (DOCS / d).rglob("*.html") if (DOCS / d).exists() else []:
            f.unlink()
    (DOCS / "index.html").write_text(index_page(cat, S, svc), encoding="utf-8")
    by_id = {c["id"]: c for c in S["collections"]}
    pages = 1
    for coll in cat.get_collections():
        out = DOCS / "collections" / f"{coll.id}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(collection_page(coll, by_id[coll.id]), encoding="utf-8")
        pages += 1
        for item in coll.get_items():
            out = DOCS / "items" / coll.id / f"{item.id}.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(item_page(coll, item), encoding="utf-8")
            pages += 1
    print(f"wrote {pages} pages")


if __name__ == "__main__":
    main()
