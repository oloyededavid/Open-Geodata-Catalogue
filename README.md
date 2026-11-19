# Open geodata catalogue

**Serving open geospatial research outputs as a static STAC catalogue and through OGC API Features (PostGIS, pygeoapi), with automated tests**

**Author:** David Oloyede · **Website:** <https://oloyededavid.github.io/Open-Geodata-Catalogue/> · **Licence:** MIT (code); each data collection keeps the licence its study states (see `LICENSE-DATA.md`)

## What it is

A catalogue of the spatial outputs of David Oloyede's open studies. Each study gets one STAC collection; each
layer it publishes (study areas, grids of results, facility points, raster maps) becomes one STAC item with its
files in open formats:

- vector layers as GeoParquet and GeoJSON in EPSG:4326 (longitude, latitude);
- rasters as Cloud-Optimised GeoTIFFs in their original grid, with a PNG quick-look.

Every file has its size and SHA-256 checksum in the STAC item. Collections link to the study page, the
repository, the licence statement and the commit the files were taken from.

The same vector layers can be loaded into PostGIS and served as OGC API Features collections by pygeoapi.

The counts (collections, items, files, bytes, features) are in `docs/data/catalogue_stats.json`, which the build
writes; the website and the design page (`paper/paper.md`, `docs/about.html`) read their numbers from it and from
`docs/data/service_check.json`. They are not repeated here.

## Why

The studies publish their results as web pages and repositories, and some of their spatial outputs exist only as
JSON or CSV written for a page's own map. A catalogue gives each layer a stable address, metadata (extent, time
range, licence, provenance) and standard formats that GIS software and code can read without going through each
repository.

## Layout

```
catalogue/sources.yaml          ingestion config: one entry per study
scripts/build_catalogue.py      sources.yaml -> docs/stac/ (+ docs/data/catalogue_stats.json, search_index.json)
scripts/converters.py           page JSON/CSV -> vector layers (grid cells, facility points, district table)
scripts/build_service_config.py docs/stac -> service/pygeoapi-config.yml
scripts/load_postgis.py         GeoParquet assets -> PostGIS tables (SRID 4326, GiST index)
scripts/service_check.py        temporary PostGIS + pygeoapi test client -> docs/data/service_check.json
scripts/build_paper.py          paper/template.md -> paper/paper.md (numbers from the JSON files)
scripts/build_site.py           docs/index.html, collections/*.html, items/*/*.html
scripts/build_page.py           paper/paper.md -> docs/about.html (pandoc)
scripts/browser_check.py        Playwright check of every page at 390 and 1440 px
scripts/pgtemp.py, run_local.py temporary PostGIS cluster; local service without Docker
service/                        pygeoapi config (generated) and the loader Dockerfile
docker-compose.yml              PostGIS + loader + pygeoapi
tests/                          catalogue, website and service tests
docs/                           the website and the catalogue (GitHub Pages root)
```

## Adding a study

Add one entry to `catalogue/sources.yaml` (id, repository name, local path, title, description, keywords, study
period, licence and the file that states it). Without a `layers` list, every GeoJSON and GeoTIFF file under the
study's `docs/data` and `outputs` folders is included. An entry whose repository, outputs, period or licence
statement is missing is skipped and listed on the website as pending. Then run `make all`.

## How to run

Python 3.13, the packages in `requirements.txt`, and pandoc for the design page.

```bash
pip install -r requirements-dev.txt
make all        # catalogue, service config, service check, paper, pages (needs the study repositories locally)
make test       # all tests
make browser    # browser check (CHANNEL=chrome if Playwright's own Chromium is not installed)
```

The local paths in `catalogue/sources.yaml` point to checkouts of the study repositories. Edit them, use `~` or
`${VAR}` in them, or set `OGC_SOURCES_ROOT` to a folder holding the checkouts (looked up by the last part of each
`path`). The build stops if a file it reads differs from git HEAD of its study repository, and records
`source_commit_on_remote` as true only when a remote-tracking branch contains that commit. Without them the committed catalogue can still be tested and served, but not rebuilt.

### The OGC API Features service

The website is static: it cannot run the API. Run it yourself in one of two ways.

With Docker:

```bash
docker compose up --build
curl "http://localhost:5000/collections?f=json"
curl "http://localhost:5000/collections/lagos_urban_heat_analytics_lga_attributes/items?f=json&limit=5&bbox=3.3,6.4,3.4,6.6"
```

Without Docker, with PostgreSQL 16 and PostGIS 3 installed (binaries in `/usr/lib/postgresql/16/bin`, or set
`PG_BIN`): `make serve` starts a temporary database, loads the layers and serves pygeoapi on
<http://localhost:5000/> until Ctrl-C, then removes the database. To use an existing database, set
`DATABASE_URL=postgresql://user:password@host:5432/dbname` for `scripts/load_postgis.py`, and `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` for pygeoapi.

The pygeoapi configuration declares the storage coordinate system as CRS84 (longitude first). Declaring
EPSG:4326 made pygeoapi swap the coordinates of every returned feature; a test guards against this.

## Publishing

The website is the `docs/` folder. In the GitHub repository settings, Pages: Source "Deploy from a branch", branch
`main`, folder `/docs`. `docs/.nojekyll` is already there.

## Tests

`pytest` runs:

- `tests/test_catalogue.py`: every STAC file validates against the STAC 1.1.0 schema and the file, projection and
  table extension schemas (kept in `tests/schemas/` so validation works offline); links are relative and resolve;
  file sizes and checksums match; GeoTIFFs are valid COGs; GeoParquet and GeoJSON agree; size limits hold; the
  stats file matches the catalogue.
- `tests/test_site.py`: every number marked on the pages equals the generated JSON; the paper matches its
  template; local links resolve; no emojis or placeholder text.
- `tests/test_service.py`: loads the layers into PostGIS (a temporary cluster, or the database in `OGC_TEST_DSN`),
  starts pygeoapi with its Flask test client, and checks `/conformance`, `/collections`, `items?limit=` with
  paging, single features and bounding-box filtering.

GitHub Actions (`.github/workflows/tests.yml`) runs the same tests against a `postgis/postgis:16-3.4` service
container.

## Limits

- The data come from the studies and keep their limits: most layers are satellite or model estimates, not
  measurements, and the study pages explain what each can and cannot show. The catalogue adds no analysis.
- Files are copies at one commit of each study. If a study changes, rebuild the catalogue.
- Only outputs stored in the study repositories are included; large intermediate rasters the studies rebuild from
  public archives are not. A converted file over 20 MB would be linked to its source repository, not copied.
- Coastal-Hydrogeology-Modeling states an MIT licence and no separate data licence, so its collection is marked
  `other`. The Mozambique collection is marked `various`: one item derived from OpenStreetMap is under the ODbL 1.0 and every item states its own licence. The Lagos boundaries (FAO GAUL, non-commercial use) and the Ogun SAR flood fields (MERIT Hydro mask, CC BY-NC or ODbL) carry a licence note in the collection.
- Sizes are in SI megabytes (1 MB = 1,000,000 bytes) everywhere.
- The pages load fonts from api.fontshare.com and, on the published site only, a reaction and page-view counter from abacus.jasoncameron.dev. Nothing else is requested from a third party.
- The service is a local demonstration. It has not been deployed, load-tested or secured. Its tests check the core,
  GeoJSON and OpenAPI behaviour by queries; no formal OGC conformance test suite was run.
- The website's map outlines are Natural Earth 1:50m African country outlines (`scripts/make_basemap.py`), too coarse for city scale, so they are
  hidden when a map is zoomed in.

## Citation

See `CITATION.cff`, and cite the study each layer comes from.
