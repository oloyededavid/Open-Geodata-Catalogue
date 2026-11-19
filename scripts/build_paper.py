"""Build paper/paper.md from paper/template.md. Every {{key}} is filled from docs/data/catalogue_stats.json and
docs/data/service_check.json; the build stops if a key is unknown or a statement in the template no longer holds.

    python scripts/build_paper.py
"""
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, ROOT, read_json  # noqa: E402

LICENCE = {"CC-BY-4.0": "CC BY 4.0", "other": "not stated", "various": "various"}
WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()


def mb(b):
    return f"{b / 1e6:.1f}"


def values():
    S = read_json(DATA / "catalogue_stats.json")
    V = read_json(DATA / "service_check.json")
    if V["n_collections"] != S["n_vector_items"] or V["n_features"] != S["n_features"]:
        raise SystemExit("service_check.json does not match the catalogue; rerun scripts/service_check.py")
    bf, ff = S["bytes_by_format"], S["files_by_format"]
    built = dt.date.fromisoformat(S["built"])
    other = [c for c in S["collections"] if c["licence_data"] == "other"]
    various = [c for c in S["collections"] if c["licence_data"] == "various"]
    noted = [c for c in S["collections"] if c["licence_data"] == "CC-BY-4.0" and c["licence_note"]]
    pending = S["n_pending"]
    rows = ["| Study | Items | Vector features | Files | MB | Period | Data licence |", "| :--- | ---: | ---: | ---: | ---: | :--- | :--- |"]
    for c in S["collections"]:
        rows.append(f"| [{c['title']}]({c['page']}) | {c['items']} | {c['features']:,} | {c['files']} | {mb(c['bytes'])} | "
                    f"{c['start'][:4]}–{c['end'][:4]} | {LICENCE.get(c['licence_data'], c['licence_data'])} |")
    linked = S["linked_only"]
    v = {
        "month_year": built.strftime("%B %Y"),
        "n_collections_word": WORDS[S["n_collections"]].capitalize(), "n_converted": WORDS[S["n_converted"]].capitalize(),
        "n_collections": S["n_collections"], "n_items": S["n_items"], "n_vector_items": S["n_vector_items"],
        "n_raster_items": S["n_raster_items"], "n_features": f"{S['n_features']:,}", "n_data_files": S["n_data_files"],
        "mb_data": mb(S["bytes_data_files"]), "n_sources_configured": S["n_sources_configured"], "skipped_sentence": ("none was skipped" if pending == 0 else f"{pending} {'was' if pending == 1 else 'were'} skipped") + " at the last build",
        "files_geoparquet": ff["geoparquet"], "mb_geoparquet": mb(bf["geoparquet"]),
        "files_geojson": ff["geojson"], "mb_geojson": mb(bf["geojson"]),
        "files_cog": ff["cog"], "mb_cog": mb(bf["cog"]), "files_preview": ff["preview"], "mb_preview": mb(bf["preview"]),
        "mb_largest": mb(S["largest_file_bytes"]), "max_file_mb": S["max_file_mb"], "max_docs_mb": S["max_docs_mb"],
        "linked_sentence": ("No file reached that limit, so every file is in the catalogue itself." if not linked else
                            f"{len(linked)} files reached that limit and are linked, not copied."),
        "n_ccby": sum(c["licence_data"] == "CC-BY-4.0" for c in S["collections"]),
        "n_various": len(various),
        "licence_notes_sentence": "Licence notes recorded with a collection: " + " ".join(
            f"{c['repo']}: {c['licence_note']}" for c in noted) if noted else "",
        "licence_other_sentence": " ".join(
            f"The {c['repo']} repository states an MIT licence and no separate licence for its derived data, so its "
            f"collection is marked “other” until the author states one." for c in other),
        "item_licence_sentence": " ".join(
            f"The {c['repo']} collection is marked “various”: each of its {len(c['items_own_licence'])} items states its own "
            f"licence ({', '.join(sorted({x['licence'] for x in c['items_own_licence']}))}), because the layer derived from "
            f"OpenStreetMap is under the ODbL, as the study states."
            for c in various),
        "svc_checked": V["checked"], "svc_pygeoapi": V["pygeoapi_version"], "svc_collections": V["n_collections"],
        "svc_features": f"{V['n_features']:,}", "svc_postgis": V["postgis_version"],
        "svc_postgresql": V["postgresql_version"].split()[0], "svc_conformance": V["conformance_classes"],
        "collections_table": "\n".join(rows),
    }
    return v


def main():
    tpl = (ROOT / "paper" / "template.md").read_text(encoding="utf-8")
    v = values()
    missing = sorted(set(re.findall(r"\{\{(\w+)\}\}", tpl)) - set(v))
    if missing:
        raise SystemExit(f"template keys without a value: {missing}")
    out = re.sub(r"\{\{(\w+)\}\}", lambda m: str(v[m.group(1)]), tpl)
    (ROOT / "paper" / "paper.md").write_text(out, encoding="utf-8")
    print("wrote paper/paper.md")


if __name__ == "__main__":
    main()
