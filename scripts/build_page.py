"""Build docs/about.html from paper/paper.md with pandoc, inside the same page shell as the rest of the site.
The numbers come from the paper build (scripts/build_paper.py), so the page and the paper cannot disagree.

    python scripts/build_paper.py && python scripts/build_page.py
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import page  # noqa: E402
from common import DOCS, ROOT  # noqa: E402


def tidy(html):
    """Keep a number and its unit together, and show DOI-less URLs in references as links."""
    parts = re.split(r"(<[^>]+>)", html)
    unit = re.compile(r"(\d) (MB|KB|km\b|m\b|%)")
    return "".join(p if p.startswith("<") else unit.sub("\\1\u00a0\\2", p) for p in parts)


def main():
    md = (ROOT / "paper" / "paper.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", md, flags=re.S)
    meta = dict(re.findall(r'^(\w+): "?([^"\n]*)"?$', m.group(1), flags=re.M))
    body_md = md[m.end():]
    r = subprocess.run(["pandoc", "-f", "markdown", "-t", "html5", "--shift-heading-level-by=1", "--wrap=none"],
                       input=body_md, capture_output=True, text=True, check=True)
    body = r.stdout
    body = re.sub(r'(<h2 id="references">References</h2>\s*)((?:<p>.*?</p>\s*)+)',
                  lambda k: k.group(1) + '<ol class="refs" role="list">\n' + "\n".join(
                      "<li>" + re.sub(r'(?<!")(https?://[^\s<]+?)([.,;]?)(?=\s|$|<)', r'<a href="\1">\1</a>\2', p) + "</li>"
                      for p in re.findall(r"<p>(.*?)</p>", k.group(2), flags=re.S)) + "\n</ol>\n", body, flags=re.S)
    body = re.sub(r"<table>", '<div class="cat-table"><table>', body).replace("</table>", "</table></div>")
    head = (f'<header class="title">\n    <p class="cat-crumbs"><a href="index.html">Catalogue</a> / Design</p>\n'
            f'    <h1>{meta["title"]}</h1>\n    <p class="sig"><span>{meta["author"]}</span><span>{meta["date"]}</span></p>\n</header>\n')
    html = page(title="Design of the catalogue – Open geodata catalogue", base="", path="about.html",
                description="How the open geodata catalogue is built: STAC, GeoParquet, Cloud-Optimised GeoTIFF, PostGIS, pygeoapi and tests.",
                toc=[("index.html#collections", "Catalogue"), ("#abstract", "Abstract"), ("#design", "Design"),
                     ("#checks", "Checks"), ("#limits", "Limits"), ("#references", "References")],
                body=head + tidy(body), scripts=(), end_nav=True)
    out = DOCS / "about.html"
    out.write_text(html, encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
