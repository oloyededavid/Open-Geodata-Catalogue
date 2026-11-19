"""The website in docs/: numbers match the generated JSON, the paper matches its template, pages are complete."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import build_paper
import build_site
from common import read_json

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = sorted(DOCS.rglob("*.html"))
PAGES = [p for p in PAGES if "vendor" not in p.parts and "assets" not in p.parts]  # assets/*.html are includes


class Spans(HTMLParser):
    """Collect (key, text) of every <span data-stat="key">text</span>, and every href/src."""
    def __init__(self):
        super().__init__()
        self.stats, self.refs, self._key, self._buf = [], [], None, ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "span" and "data-stat" in a:
            self._key, self._buf = a["data-stat"], ""
        for k in ("href", "src"):
            if a.get(k):
                self.refs.append(a[k])
        for k in ("data-geojson", "data-preview"):
            if a.get(k):
                self.refs.append(a[k])

    def handle_data(self, data):
        if self._key is not None:
            self._buf += data

    def handle_endtag(self, tag):
        if tag == "span" and self._key is not None:
            self.stats.append((self._key, self._buf))
            self._key = None


def expected(key, S, V):
    if key.startswith("c:"):
        _, cid, field = key.split(":")
        c = next(x for x in S["collections"] if x["id"] == cid)
        return build_site.years(c["start"], c["end"]) if field == "years" else str(c[field])
    if key.startswith("svc:"):
        f = key[4:]
        return build_site.n(V[f]) if f == "n_features" else str(V[f])
    if key == "mb_data_files":
        return build_site.mb(S["bytes_data_files"])
    if key == "n_features":
        return build_site.n(S["n_features"])
    return str(S[key])


def test_every_number_on_the_pages_comes_from_the_generated_files():
    S = read_json(DOCS / "data" / "catalogue_stats.json")
    V = read_json(DOCS / "data" / "service_check.json")
    seen = 0
    for p in PAGES:
        sp = Spans()
        sp.feed(p.read_text(encoding="utf-8"))
        for key, text in sp.stats:
            assert text == expected(key, S, V), f"{p.name}: {key} shows {text!r}"
            seen += 1
    assert seen >= 20


def test_index_numbers_are_marked():
    """Digits in the index page's running text appear only inside data-stat spans, code, or links and attributes."""
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    main = html[html.index("<main"):html.index("</main>")]
    main = re.sub(r'<span data-stat="[^"]*">[^<]*</span>', "", main)
    main = re.sub(r"<(pre|code|select|script)[^>]*>.*?</\1>", "", main, flags=re.S)
    main = re.sub(r'<p class="cat-desc">.*?</p>', "", main, flags=re.S)  # descriptions from catalogue/sources.yaml
    text = re.sub(r"<[^>]+>", " ", main)
    for word in ("CC BY 4.0", "STAC 1.1", "EPSG:4326", "SHA-256", "2nd", "98th"):
        text = text.replace(word, "")
    assert not re.findall(r"\d", text), re.findall(r".{30}\d.{30}", text)[:5]


def test_paper_is_built_from_template_and_page_from_paper():
    v = build_paper.values()
    tpl = (ROOT / "paper" / "template.md").read_text(encoding="utf-8")
    built = re.sub(r"\{\{(\w+)\}\}", lambda m: str(v[m.group(1)]), tpl)
    assert built == (ROOT / "paper" / "paper.md").read_text(encoding="utf-8"), "rerun scripts/build_paper.py"
    about = (DOCS / "about.html").read_text(encoding="utf-8")
    assert "{{" not in about
    for num in (str(v["n_items"]), v["n_features"], v["mb_data"]):
        assert num in about


def test_local_links_and_assets_resolve():
    for p in PAGES:
        sp = Spans()
        sp.feed(p.read_text(encoding="utf-8"))
        for ref in sp.refs:
            if ref.startswith(("http:", "https:", "mailto:", "data:", "#")):
                continue
            target = (p.parent / ref.split("#")[0].split("?")[0]).resolve()
            assert target.exists(), f"{p.relative_to(DOCS)}: {ref}"


def test_pages_are_plain():
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-⛿✀-➿]")
    for p in PAGES + [ROOT / "README.md", ROOT / "paper" / "paper.md"]:
        t = p.read_text(encoding="utf-8")
        assert not emoji.search(t), p
        assert not re.search(r"\b(Claude|Anthropic)\b", t), p
        assert "/home/user" not in t, p
        assert not re.search(r"\b(novel|first-ever|groundbreaking|cutting-edge)\b", t, flags=re.I), p
    for p in PAGES:
        t = p.read_text(encoding="utf-8")
        assert re.search(r"<title>[^<]+</title>", t) and 'lang="en"' in t, p


def test_search_index_and_footprints_cover_all_items():
    idx = read_json(DOCS / "data" / "search_index.json")
    fp = json.loads((DOCS / "data" / "footprints.geojson").read_text())
    assert {(e["collection"], e["id"]) for e in idx} == {(f["properties"]["collection"], f["properties"]["id"]) for f in fp["features"]}
