/* Catalogue pages: extent maps (vendored Leaflet, no tile server: outlines from Natural Earth), the item
   search on the index page and the map on collection and item pages. Everything runs in the browser from
   files in this site. <body data-base="../"> gives the path from the page to the site root. */
(() => {
    'use strict';
    const base = document.body.dataset.base || '';
    const $ = (s, r = document) => r.querySelector(s);
    const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
    const getJSON = u => fetch(u).then(r => (r.ok ? r.json() : Promise.reject(new Error(`${u}: ${r.status}`))));
    const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    let basemap = null;
    const outlines = () => basemap || (basemap = getJSON(`${base}assets/basemap.geojson`));
    let footprints = null;
    const prints = () => footprints || (footprints = getJSON(`${base}data/footprints.geojson`));
    const INK = '#1f56b0', LAND = '#ffffff', EDGE = '#b9bcc2';

    function makeMap(el, interactive) {
        const opts = interactive ? { zoomSnap: 0.25, scrollWheelZoom: false } : {
            zoomSnap: 0.1, dragging: false, touchZoom: false, scrollWheelZoom: false, doubleClickZoom: false,
            boxZoom: false, keyboard: false, zoomControl: false, attributionControl: false,
        };
        const m = L.map(el, opts);
        if (interactive) {
            m.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
            m.attributionControl.addAttribution('Outlines: Natural Earth');
        }
        // raster quick-looks go in their own pane above the vector layers, so the land fill cannot hide them;
        // the outlines are too coarse at city scale, so they are hidden when zoomed in
        m.createPane('raster').style.zIndex = 450;
        outlines().then(g => {
            const base = L.geoJSON(g, { interactive: false, style: { color: EDGE, weight: 1, fillColor: LAND, fillOpacity: 1 } });
            const toggle = () => (m.getZoom() < 8 ? base.addTo(m).bringToBack() : base.remove());
            m.on('zoomend', toggle);
            toggle();
        }).catch(() => {});
        return m;
    }
    const boundsOf = b => L.latLngBounds([b[1], b[0]], [b[3], b[2]]);

    // ---------- card thumbnails: the collection extent and its item footprints, in context ----------
    const thumbs = $$('[data-thumb]');
    if (thumbs.length) {
        prints().then(fp => thumbs.forEach(el => {
            const id = el.dataset.thumb, bbox = JSON.parse(el.dataset.bbox);
            const m = makeMap(el, false);
            const b = boundsOf(bbox);
            m.fitBounds(b.pad(1.6));
            L.rectangle(b, { color: INK, weight: 1, dashArray: '3 3', fill: false, interactive: false }).addTo(m);
            L.geoJSON({ type: 'FeatureCollection', features: fp.features.filter(f => f.properties.collection === id) }, {
                interactive: false, style: { color: INK, weight: 1.2, fillColor: INK, fillOpacity: 0.12 },
            }).addTo(m);
        })).catch(err => console.warn('footprints not loaded', err));
    }

    // ---------- collection page: all item footprints ----------
    const cmap = $('#collection-map');
    if (cmap) {
        prints().then(fp => {
            const id = cmap.dataset.collection;
            const m = makeMap(cmap, true);
            const layer = L.geoJSON({ type: 'FeatureCollection', features: fp.features.filter(f => f.properties.collection === id) }, {
                style: f => ({ color: INK, weight: 1.4, fillColor: INK, fillOpacity: f.properties.kind === 'raster' ? 0.04 : 0.14 }),
                onEachFeature: (f, l) => l.bindTooltip(esc(f.properties.title)),
            }).addTo(m);
            m.fitBounds(layer.getBounds().pad(0.15));
        }).catch(err => console.warn('footprints not loaded', err));
    }

    // ---------- item page: the data themselves (vector) or the quick-look (raster) ----------
    const imap = $('#item-map');
    if (imap) {
        const bbox = JSON.parse(imap.dataset.bbox);
        const m = makeMap(imap, true);
        const b = boundsOf(bbox);
        m.fitBounds(b.pad(0.1));
        if (imap.dataset.geojson) {
            getJSON(imap.dataset.geojson).then(g => {
                const keys = JSON.parse(imap.dataset.keys || '[]');
                L.geoJSON(g, {
                    style: { color: INK, weight: 1.2, fillColor: INK, fillOpacity: 0.15 },
                    // points as small circles (the default marker images are not shipped)
                    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3, color: INK, weight: 1, fillColor: INK, fillOpacity: 0.5 }),
                    onEachFeature: (f, l) => {
                        const p = f.properties || {};
                        const rows = keys.filter(k => k in p).map(k => `<b>${esc(k)}</b>: ${esc(p[k] === null ? '–' : p[k])}`);
                        if (rows.length) l.bindTooltip(rows.join('<br>'), { sticky: true });
                    },
                }).addTo(m);
            }).catch(err => console.warn('layer not loaded', err));
        } else if (imap.dataset.preview) {
            L.imageOverlay(imap.dataset.preview, b, { pane: 'raster', opacity: 0.9, alt: imap.dataset.alt || '' }).addTo(m);
            L.rectangle(b, { color: INK, weight: 1, fill: false, interactive: false }).addTo(m);
        }
    }

    // ---------- search over all items ----------
    const q = $('#q'), list = $('#results');
    if (q && list) {
        const kind = $('#kind'), coll = $('#coll'), status = $('#search-status');
        getJSON(`${base}data/search_index.json`).then(index => {
            const hay = index.map(e => [e.title, e.description, e.collection_title, e.id, e.collection, e.kind, ...(e.keywords || [])].join(' ').toLowerCase());
            const years = e => (e.start.slice(0, 4) === e.end.slice(0, 4) ? e.start.slice(0, 4) : `${e.start.slice(0, 4)}–${e.end.slice(0, 4)}`);
            const render = () => {
                const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
                const hits = index.filter((e, i) => (!kind.value || e.kind === kind.value) && (!coll.value || e.collection === coll.value)
                    && terms.every(t => hay[i].includes(t)));
                list.innerHTML = hits.map(e => `<li><a href="${esc(e.page)}">${esc(e.title)}</a><span class="r-kind">${esc(e.kind)}</span>`
                    + `<span class="r-meta">${esc(e.collection_title)} · ${years(e)}${e.features ? ` · ${e.features.toLocaleString('en-GB')} features` : ''}</span></li>`).join('');
                status.textContent = hits.length === index.length ? `Showing all ${index.length} items.` : `${hits.length} of ${index.length} items match.`;
            };
            [q, kind, coll].forEach(el => el.addEventListener('input', render));
            render();
        }).catch(err => { status.textContent = 'The search index could not be loaded.'; console.warn(err); });
    }
})();
