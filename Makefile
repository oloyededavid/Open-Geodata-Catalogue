# Build order: catalogue -> service config -> service check -> paper -> pages. `make all` runs them in order.
# Building the catalogue needs the study repositories at the paths in catalogue/sources.yaml.
PY ?= python3
SCRATCH ?= build/browser

.PHONY: all catalogue service-config service-check paper site test browser serve compose

all: catalogue service-config service-check paper site

catalogue:
	$(PY) scripts/build_catalogue.py

service-config:
	$(PY) scripts/build_service_config.py

service-check:   ## temporary PostGIS (or DATABASE_URL), load, query; writes docs/data/service_check.json
	$(PY) scripts/service_check.py

paper:
	$(PY) scripts/build_figures.py
	$(PY) scripts/build_paper.py

site:
	$(PY) scripts/build_site.py
	$(PY) scripts/build_page.py

test:
	$(PY) -m pytest -q

browser:         ## Playwright check of every page at 390 and 1440 px; add CHANNEL=chrome if needed
	$(PY) scripts/browser_check.py --out $(SCRATCH) $(if $(CHANNEL),--channel $(CHANNEL))

serve:           ## local OGC API Features service on http://localhost:5000 (temporary PostGIS)
	$(PY) scripts/run_local.py

compose:         ## the same with Docker
	docker compose up --build
