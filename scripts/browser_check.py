"""Open every page of docs/ in a headless browser at phone (390 px) and desktop (1440 px) width.

Fails on console errors, page errors, failed requests to the local server, horizontal overflow, maps that did
not draw, or a local link that does not return 200. Saves screenshots of a sample of pages and a JSON report.

    python scripts/browser_check.py [--out DIR] [--channel chrome]
Requires Playwright (pip install playwright; playwright install chromium).
"""
import argparse
import functools
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DOCS  # noqa: E402

WIDTHS = {"phone": (390, 844), "desktop": (1440, 900)}
SHOTS = ["index.html", "about.html", "collections/oueme-ogun-groundwater-recharge.html",
         "items/lagos-urban-heat-analytics/lga-attributes.html", "items/coastal-hydrogeology-modeling/arpi-2024.html",
         "items/mozambique-health-access/facilities-public-and-herams.html"]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    handler = functools.partial(Quiet, directory=str(DOCS))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def main():
    from playwright.sync_api import sync_playwright
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/browser")
    ap.add_argument("--channel", default=None, help="browser channel, e.g. chrome, if Playwright's own is missing")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    httpd, root = serve()
    pages = sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.html")
                   if "vendor" not in p.parts and "assets" not in p.parts)
    report = {"pages": len(pages), "widths": list(WIDTHS), "problems": [], "links_checked": 0, "external_links": 0,
              "screenshots": []}
    links = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=a.channel) if a.channel else pw.chromium.launch()
        for wname, (w, h) in WIDTHS.items():
            ctx = browser.new_context(viewport={"width": w, "height": h})
            for rel in pages:
                pg = ctx.new_page()
                errors = []
                pg.on("console", lambda m, e=errors: e.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
                pg.on("pageerror", lambda exc, e=errors: e.append(f"page error: {exc}"))
                pg.on("requestfailed", lambda r, e=errors: e.append(f"request failed: {r.url}") if r.url.startswith(root) else None)
                pg.on("response", lambda r, e=errors: e.append(f"HTTP {r.status}: {r.url}") if r.url.startswith(root) and r.status >= 400 else None)
                pg.goto(root + rel, wait_until="load")
                pg.wait_for_timeout(700)
                over = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 0:
                    errors.append(f"horizontal overflow of {over}px")
                maps = pg.evaluate("""() => Array.from(document.querySelectorAll('.leaflet-container')).map(m =>
                    m.querySelectorAll('path').length + m.querySelectorAll('img.leaflet-image-layer').length)""")
                expect = pg.evaluate("() => document.querySelectorAll('[data-thumb], #item-map, #collection-map').length")
                if len(maps) != expect or any(c == 0 for c in maps):
                    errors.append(f"maps: expected {expect} drawn, got {maps}")
                if rel == "index.html":
                    n = pg.evaluate("() => document.querySelectorAll('#results li').length")
                    pg.fill("#q", "surplus 2020")
                    pg.wait_for_timeout(200)
                    m = pg.evaluate("() => document.querySelectorAll('#results li').length")
                    if not (n > m > 0):
                        errors.append(f"search: {n} items listed, {m} after filtering")
                for href in pg.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))"):
                    full = urljoin(root + rel, href)
                    if full.startswith(root):
                        links.add(full.split("#")[0])
                    elif urlparse(full).scheme in ("http", "https"):
                        report["external_links"] += 1
                if rel in SHOTS:
                    shot = out / f"{rel.replace('/', '_').replace('.html', '')}_{wname}.png"
                    pg.screenshot(path=str(shot), full_page=True)
                    report["screenshots"].append(str(shot))
                for e in errors:
                    report["problems"].append(f"{wname} {rel}: {e}")
                pg.close()
            ctx.close()
        req = pw.request.new_context()
        for u in sorted(links):
            r = req.get(u)
            report["links_checked"] += 1
            if r.status != 200:
                report["problems"].append(f"link {u}: HTTP {r.status}")
        req.dispose()
        browser.close()
    httpd.shutdown()
    (out / "browser_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{report['pages']} pages x {len(WIDTHS)} widths, {report['links_checked']} local links checked, "
          f"{report['external_links']} external links not checked, {len(report['problems'])} problems")
    for p in report["problems"]:
        print("  ", p)
    sys.exit(1 if report["problems"] else 0)


if __name__ == "__main__":
    main()
