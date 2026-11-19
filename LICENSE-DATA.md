# Data licence

The catalogue does not create new data. Every file under `docs/stac/` is a copy or a format conversion
(GeoParquet, GeoJSON, Cloud-Optimised GeoTIFF, PNG quick-look) of an output of one of the studies below, and
keeps the licence that study states. Each STAC collection records it in `license` and links to the statement.

| Collection | Data licence | Stated in |
| :--- | :--- | :--- |
| observational-hydrology-extremes | CC BY 4.0 | README.md of Observational-Hydrology-Extremes |
| ogun-catchment-coast-observatory | CC BY 4.0; the SAR flood fields use a MERIT Hydro mask (CC BY-NC 4.0 or ODbL 1.0), so check its terms before commercial use | LICENSE-DATA.md of Ogun-Catchment-Coast-Observatory |
| oueme-ogun-groundwater-recharge | CC BY 4.0 | LICENSE-DATA.md of Oueme-Ogun-Groundwater-Recharge |
| groundwater-storage-gravimetry | CC BY 4.0 | README.md of Groundwater-Storage-Gravimetry |
| lagos-urban-heat-analytics | CC BY 4.0, except the LGA boundaries (FAO GAUL 2015, non-commercial use only) | LICENSE-DATA.md of Lagos-Urban-Heat-Analytics |
| coastal-hydrogeology-modeling | not stated separately (`other`) | README.md of Coastal-Hydrogeology-Modeling states MIT for the repository |
| mozambique-health-access | `various`: items `district-access-public-list` and `facilities-public-and-herams` CC BY 4.0; item `facilities-openstreetmap` ODbL 1.0 (© OpenStreetMap contributors) | LICENSE-DATA.md of Mozambique-Health-Access |

Where a study states a restriction on part of its data, the collection carries it as `geocat:licence_note` and the website shows it.

The source datasets behind the studies (CHIRPS, WaPOR, GRACE/GRACE-FO, Landsat, Sentinel, HydroBASINS and
others) keep their own terms, listed in each study repository. Country outlines used on the website
(`docs/assets/basemap.geojson`, made by `scripts/make_basemap.py`) are from Natural Earth 1:50m (public domain).

The catalogue's own metadata (the STAC JSON files, `docs/data/*.json`) and the website text are released
under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/
