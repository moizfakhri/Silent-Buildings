/* Complaint gap map: static MapLibre app. No build step, no server code, no external tiles.
   Data: data/buildings.pmtiles (or data/sample/*.geojson), data/districts.json, data/facts/*.json (see pipelines/build_map.py).
   Every score series is a string of 16 three-digit numbers (one per snapshot); 999 = no value. */
(function () {
  "use strict";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: fine */ } },
  };
  const $ = (id) => document.getElementById(id);
  const NULLCOL = "#8a8f98";
  const SEQ = [[0, "#f7f4e9"], [250, "#fdd49e"], [500, "#fc8d59"], [750, "#d7301f"], [998, "#7f0000"]];
  const SEQ2 = [[0, "#f1f4f9"], [250, "#bcd4ea"], [500, "#6aaee8"], [750, "#2166ac"], [998, "#08306b"]];
  const DIV = [[0, "#2166ac"], [250, "#92c5de"], [499, "#f2f2f2"], [750, "#f4a582"], [998, "#b2182b"]];

  const LAYERS = {
    risk: { key: "r", label: "Predicted risk of an enforcement event", ramp: SEQ, lo: "lower", hi: "higher", unit: "percentile within the snapshot",
      help: "A model estimate of how likely the building is to see a vacate order, an emergency repair charge, an AEP selection or an HPD litigation in the next 12 months. It uses violations, complaints and earlier city actions, so it largely reflects how much the city is already involved with the building. Colours are percentiles within the snapshot." },
    cond: { key: "c", label: "Predicted condition (no complaint information)", ramp: SEQ, lo: "lower", hi: "higher", unit: "percentile within the snapshot",
      help: "A model estimate of the risk of a vacate order or a DOB physical-hazard violation in the next 12 months, using only age, size, building class and earlier city actions: no complaints and no violations. It is a rough proxy for condition, not a measurement." },
    gap: { key: "g", label: "Complaint gap: predicted condition vs complaints", ramp: DIV, lo: "louder than predicted", hi: "quieter than predicted", unit: "difference of within-borough percentiles",
      help: "Compares a building's predicted condition (previous layer) with its complaint record (shrunk complaint problems per unit, within borough). Warm = quieter than its predicted condition suggests; cool = louder. What it does NOT mean: in the validation behind this map, buildings in the top 10% of the gap had about 16% FEWER later vacate or DOB-hazard events than the model predicted, not more, and 35% fewer than comparable louder buildings. Silence is ordinary: about 77% of buildings have no HPD complaint in a year. Treat this as a research diagnostic, not a list of problem buildings." },
    access: { key: "a", label: "Share of closed complaints with no inspector access", ramp: SEQ2, lo: "0%", hi: "100%", unit: "share of problems closed in the last 12 months",
      help: "Of the complaint problems closed in the last 12 months, the share that closed because the inspector was not able to gain access. Grey = nothing closed. The mechanism is real and sizeable (about 16% of closed problems overall), but buildings with a high share did not show extra later risk compared with similar buildings with better access." },
    comp: { key: "m", label: "Observed complaints per unit (12 months)", ramp: SEQ2, lo: "0", hi: "2 or more per unit", unit: "HPD complaint problems per residential unit",
      help: "HPD complaint problems filed in the 12 months before the snapshot, divided by the number of residential units. It measures reporting as much as conditions." },
  };

  let meta = null, snaps = [], idx = 15, layerKey = "risk", mode = "tiles", map, districts = null, factsCache = {}, sampleFacts = null, timer = null;
  const districtById = {};
  // District view (zoomed out): colours are district AVERAGES on their own scale, computed here from the averages in districts.json.
  const DNAME = { risk: "risk", cond: "cond", gap: "gap", access: "nacc", comp: "comp" };
  const DISTRICT_ZOOM = 12.3;          // below this the district layer is what you see
  const dscale = {};
  let districtView = false, selected = "";
  function buildDistrictScales() {
    Object.entries(DNAME).forEach(([lk, name]) => {
      const all = [];
      districts.features.forEach((f) => (f.properties.v[name] || []).forEach((x) => { if (x != null) all.push(x); }));
      let lo = Math.min(...all), hi = Math.max(...all);
      if (lk === "gap") { hi = Math.max(Math.abs(lo), Math.abs(hi)); lo = -hi; }      // diverging ramp: zero must sit at the neutral midpoint
      dscale[lk] = [lo, hi];
      districts.features.forEach((f) => {
        f.properties[LAYERS[lk].key] = (f.properties.v[name] || []).map((x) =>
          String(x == null ? 999 : Math.max(0, Math.min(998, Math.round(((x - lo) / (hi - lo || 1)) * 998)))).padStart(3, "0")).join("");
      });
    });
  }
  const dfmt = (lk, x) => (lk === "risk" || lk === "cond" ? (100 * x).toFixed(lk === "cond" ? 2 : 1) + "%"
    : lk === "access" ? (100 * x).toFixed(0) + "%" : lk === "gap" ? (x > 0 ? "+" : "") + x.toFixed(2) : x.toFixed(2));

  const val = (key, i) => ["to-number", ["slice", ["get", key], i * 3, i * 3 + 3], 999];
  function colorExpr(L, i) {
    const stops = [];
    L.ramp.forEach(([s, c]) => stops.push(s, c));
    return ["case", ["==", val(L.key, i), 999], NULLCOL, ["interpolate", ["linear"], val(L.key, i), ...stops]];
  }
  function filterExpr() {
    const f = ["all"];
    const b = $("borough").value, d = $("district").value;
    if (b) f.push(["==", ["get", "bo"], b]);
    if (d) f.push(["==", ["get", "cd"], d]);
    if ($("only-gap").checked) f.push(["==", ["slice", ["get", "sf"], idx, idx + 1], "1"]);
    if ($("only-access").checked) f.push(["==", ["slice", ["get", "ab"], idx, idx + 1], "1"]);
    return f.length > 1 ? f : null;
  }
  const theme = () => document.documentElement.dataset.theme;
  const bgColor = () => (theme() === "dark" ? "#14171c" : "#e9ecf1");
  const ctxColor = () => (theme() === "dark" ? "#3b414b" : "#c4c9d2");

  function renderLegend() {
    const L = LAYERS[layerKey];
    const grad = L.ramp.map(([s, c]) => `${c} ${(s / 998) * 100}%`).join(", ");
    const dv = districtView && dscale[layerKey];
    const lo = dv ? dfmt(layerKey, dscale[layerKey][0]) + (layerKey === "gap" ? " (louder)" : "") : L.lo;
    const hi = dv ? dfmt(layerKey, dscale[layerKey][1]) + (layerKey === "gap" ? " (quieter)" : "") : L.hi;
    const unit = dv ? "District averages. Zoom in to see individual buildings" : L.unit;
    $("legend").innerHTML = `<div class="ramp" style="background:linear-gradient(90deg, ${grad})"></div>
      <div class="ramp-labels"><span>${lo}</span><span>${hi}</span></div>
      <div class="note">${unit}. <span class="swatch" style="background:${NULLCOL}"></span>no value</div>`;
    $("help").textContent = L.help;
  }

  function applyStyle() {
    const L = LAYERS[layerKey];
    const c = colorExpr(L, idx);
    if (map.getLayer("scored")) map.setPaintProperty("scored", "fill-extrusion-color", c);
    if (map.getLayer("districts-fill")) map.setPaintProperty("districts-fill", "fill-color", c);
    const f = filterExpr();
    if (map.getLayer("scored")) map.setFilter("scored", f);
    if (map.getLayer("districts-fill")) {
      const b = $("borough").value;
      map.setFilter("districts-fill", b ? ["==", ["get", "bo"], b] : null);
      map.setFilter("districts-line", b ? ["==", ["get", "bo"], b] : null);
    }
    $("snap-label").textContent = snaps[idx];
    $("slider").value = idx;
    renderLegend();
    writeHash();
    if (!$("panel").hidden && current) renderPanel(current);
  }

  // ------------------------------------------------------------------ shareable links: #l=<layer>&s=<snapshot>&v=<lng,lat,zoom,pitch,bearing>
  function readHash() {
    const h = new URLSearchParams(location.hash.slice(1)), out = {};
    if (LAYERS[h.get("l")]) out.layer = h.get("l");
    if (h.get("s") && /^\d+$/.test(h.get("s"))) out.idx = +h.get("s");
    const v = (h.get("v") || "").split(",").map(Number);
    if (v.length === 5 && v.every((x) => Number.isFinite(x))) out.view = v;
    return out;
  }
  let hashTimer = null;
  function writeHash() {
    if (!map) return;
    clearTimeout(hashTimer);
    hashTimer = setTimeout(() => {
      const c = map.getCenter();
      const v = [c.lng.toFixed(5), c.lat.toFixed(5), map.getZoom().toFixed(2), map.getPitch().toFixed(0), map.getBearing().toFixed(0)].join(",");
      try { history.replaceState(null, "", `${location.pathname}${location.search}#l=${layerKey}&s=${idx}&v=${v}`); } catch (e) { /* file:// or sandboxed: fine */ }
    }, 250);
  }
  function setSelected(bbl) {
    selected = bbl || "";
    if (map && map.getLayer("selected")) map.setFilter("selected", ["==", ["get", "b"], selected]);
  }

  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    $("theme").textContent = t === "dark" ? "Light mode" : "Dark mode";
    store.set("cgm-theme", t);
    if (!map || !map.isStyleLoaded()) return;
    map.setPaintProperty("bg", "background-color", bgColor());
    if (map.getLayer("context")) map.setPaintProperty("context", "fill-extrusion-color", ctxColor());
    if (map.getLayer("districts-line")) map.setPaintProperty("districts-line", "line-color", t === "dark" ? "#c8cdd6" : "#4a5260");
  }

  async function head(url) {
    try { return (await fetch(url, { method: "HEAD" })).ok; } catch (e) { return false; }
  }

  async function init() {
    const stored = store.get("cgm-theme");
    setTheme(stored || (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
    try { meta = await (await fetch("data/meta.json")).json(); } catch (e) { meta = null; }
    const hasTiles = !new URLSearchParams(location.search).has("sample") && await head("data/buildings.pmtiles");
    mode = hasTiles ? "tiles" : "sample";
    let sampleGeo = null;
    if (mode === "sample") {
      sampleGeo = await (await fetch("data/sample/buildings.geojson")).json();
      snaps = sampleGeo.snapshots;
    } else {
      snaps = meta.snapshots;
    }
    try { districts = await (await fetch("data/districts.json")).json(); } catch (e) { districts = null; }
    if (districts) { districts.features.forEach((f) => { districtById[f.properties.cd] = f.properties; }); buildDistrictScales(); }
    idx = snaps.length - 1;
    $("slider").max = snaps.length - 1;
    const start = readHash();
    if (start.layer) layerKey = start.layer;
    if (start.idx != null && start.idx < snaps.length) idx = start.idx;
    const sampleCd = mode === "sample" ? (sampleGeo.features[0] && sampleGeo.features[0].properties.cd) : null;
    if (mode === "sample") {
      const p = districtById[sampleCd];
      $("sample-note").hidden = false;
      $("sample-note").innerHTML = `<strong>Sample data.</strong> Individual buildings are loaded for one community district only (${p && p.bo === "BK" ? "Brooklyn" : "Bronx"} ${sampleCd}, ${sampleGeo.features.length.toLocaleString()} footprints). Zoom out for district averages across both boroughs. The full building layer is built locally with <code>make map</code>.`;
    }

    Object.entries(LAYERS).forEach(([k, L]) => { const o = document.createElement("option"); o.value = k; o.textContent = L.label; $("layer").appendChild(o); });
    $("layer").value = layerKey;
    $("snap-label").textContent = snaps[idx];
    renderLegend();
    if (districts) {
      districts.features.map((f) => f.properties).sort((a, b) => (a.bo + a.cd).localeCompare(b.bo + b.cd)).forEach((p) => {
        const o = document.createElement("option"); o.value = p.cd; o.textContent = `${p.bo === "BK" ? "Brooklyn" : "Bronx"} district ${p.cd}`; $("district").appendChild(o);
      });
    }

    if (mode === "tiles") {
      const protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      protocol.add(new pmtiles.PMTiles(new URL("data/buildings.pmtiles", location.href).href));
    }
    const centre = mode === "sample" ? sampleCentre(sampleGeo) : [-73.915, 40.7];
    const sv = start.view;
    map = new maplibregl.Map({
      container: "map", center: sv ? [sv[0], sv[1]] : centre, zoom: sv ? sv[2] : (mode === "sample" ? 14.2 : 10.4), pitch: sv ? sv[3] : 52, bearing: sv ? sv[4] : -18,
      maxPitch: 75, minZoom: 9, attributionControl: false,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": bgColor() } }] },
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Building footprints and records: NYC Open Data · model estimates: this project · MapLibre" }));
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      if (mode === "tiles") {
        map.addSource("bld", { type: "vector", url: "pmtiles://" + new URL("data/buildings.pmtiles", location.href).href, minzoom: 11, maxzoom: 16 });
        map.addLayer({ id: "context", type: "fill-extrusion", source: "bld", "source-layer": "context", minzoom: 14,
          paint: { "fill-extrusion-color": ctxColor(), "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.55 } });
        map.addLayer({ id: "scored", type: "fill-extrusion", source: "bld", "source-layer": "scored", minzoom: 12,
          paint: { "fill-extrusion-color": colorExpr(LAYERS[layerKey], idx), "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0,
            "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 12.2, 0, 13.4, 0.93] } });
      } else {
        map.addSource("bld", { type: "geojson", data: sampleGeo });
        map.addLayer({ id: "scored", type: "fill-extrusion", source: "bld",
          paint: { "fill-extrusion-color": colorExpr(LAYERS[layerKey], idx), "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.93 } });
      }
      if (districts) {
        map.addSource("districts", { type: "geojson", data: districts });
        map.addLayer({ id: "districts-fill", type: "fill", source: "districts", paint: { "fill-color": colorExpr(LAYERS[layerKey], idx),
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], 11.6, 0.8, 13.0, 0] } }, "scored");
        map.addLayer({ id: "districts-line", type: "line", source: "districts", paint: { "line-color": theme() === "dark" ? "#c8cdd6" : "#4a5260", "line-width": 1,
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 11.6, 0.8, 13.0, 0] } }, "scored");
        map.on("mousemove", "districts-fill", (e) => hoverDistrict(e));
        map.on("mouseleave", "districts-fill", () => { $("hover").hidden = true; map.getCanvas().style.cursor = ""; });
        map.on("click", "districts-fill", (e) => { if (map.getZoom() < 12.6) { const p = e.features[0].properties; focusDistrict(p.cd); } });
      }
      // the clicked building, drawn slightly taller in a contrasting colour
      const selSrc = mode === "tiles" ? { source: "bld", "source-layer": "scored" } : { source: "bld" };
      map.addLayer({ id: "selected", type: "fill-extrusion", ...selSrc, filter: ["==", ["get", "b"], selected],
        paint: { "fill-extrusion-color": "#19d3ff", "fill-extrusion-height": ["+", ["get", "h"], 1.5], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.95 } });
      if (mode === "sample" && districts) {
        map.addLayer({ id: "sample-outline", type: "line", source: "districts", filter: ["==", ["get", "cd"], sampleCd],
          paint: { "line-color": "#19d3ff", "line-width": 1.5, "line-dasharray": [2, 2] } });
      }
      const onZoom = () => { const dvw = !!districts && map.getZoom() < DISTRICT_ZOOM; if (dvw !== districtView) { districtView = dvw; renderLegend(); } };
      map.on("zoom", onZoom);
      map.on("moveend", writeHash);
      districtView = !!districts && map.getZoom() < DISTRICT_ZOOM;
      $("layer").value = layerKey;
      map.on("mousemove", "scored", (e) => hoverBuilding(e));
      map.on("mouseleave", "scored", () => { $("hover").hidden = true; map.getCanvas().style.cursor = ""; });
      map.on("click", "scored", (e) => { if (e.features && e.features.length) openPanel(e.features[0].properties); });
      applyStyle();
    });
  }

  function sampleCentre(g) {
    let xs = 0, ys = 0, n = 0;
    for (const f of g.features.slice(0, 400)) {
      const c = (f.geometry.type === "Polygon" ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0])[0];
      xs += c[0]; ys += c[1]; n++;
    }
    return [xs / n, ys / n];
  }

  function hoverDistrict(e) {
    const p = districtById[e.features[0].properties.cd];
    if (!p) return;
    const L = LAYERS[layerKey];
    const names = DNAME;
    const series = p.v && (typeof p.v === "string" ? JSON.parse(p.v) : p.v);
    const x = series && series[names[layerKey]] ? series[names[layerKey]][idx] : null;
    const fmt = layerKey === "risk" || layerKey === "cond" ? (x == null ? "no value" : (100 * x).toFixed(2) + "% average predicted")
      : layerKey === "access" ? (x == null ? "no value" : (100 * x).toFixed(0) + "% average share")
      : layerKey === "comp" ? (x == null ? "no value" : x.toFixed(2) + " per unit on average") : (x == null ? "no value" : "average gap " + x.toFixed(2));
    const h = $("hover");
    h.innerHTML = `<strong>${p.bo === "BK" ? "Brooklyn" : "Bronx"} community district ${p.cd}</strong><br>${p.n.toLocaleString()} buildings in this analysis<br>${L.label}: ${fmt}<br><span class="note">District averages, approximate shape. Zoom in for buildings.</span>`;
    h.style.left = e.point.x + 14 + "px"; h.style.top = e.point.y + 14 + "px"; h.hidden = false; map.getCanvas().style.cursor = "pointer";
  }
  function hoverBuilding(e) {
    const p = e.features[0].properties;
    const h = $("hover");
    h.innerHTML = `${p.u} units · ${p.yb ? "built " + p.yb : "year unknown"} · ${Math.round(p.h / 0.3048)} ft<br><span class="note">Click for details</span>`;
    h.style.left = e.point.x + 14 + "px"; h.style.top = e.point.y + 14 + "px"; h.hidden = false; map.getCanvas().style.cursor = "pointer";
  }

  function bboxOf(geom) {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    const walk = (c) => { if (typeof c[0] === "number") { x0 = Math.min(x0, c[0]); x1 = Math.max(x1, c[0]); y0 = Math.min(y0, c[1]); y1 = Math.max(y1, c[1]); } else c.forEach(walk); };
    walk(geom.coordinates);
    return [[x0, y0], [x1, y1]];
  }
  function focusDistrict(cd) {
    $("district").value = cd;
    const f = districts.features.find((x) => x.properties.cd === cd);
    if (f) map.fitBounds(bboxOf(f.geometry), { padding: 60, pitch: 55, maxZoom: 14.6, duration: 900 });
    applyStyle();
  }

  // ------------------------------------------------------------------ building panel
  let current = null;
  async function getFacts(bbl) {
    if (mode === "sample") { if (!sampleFacts) sampleFacts = await (await fetch("data/sample/facts.json")).json(); return sampleFacts[bbl]; }
    const k = bbl.slice(0, 5);
    if (!factsCache[k]) { try { factsCache[k] = await (await fetch(`data/facts/${k}.json`)).json(); } catch (e) { factsCache[k] = {}; } }
    return factsCache[k][bbl];
  }
  async function openPanel(p) {
    current = p;
    setSelected(p.b);
    $("panel").hidden = false;
    $("panel-body").innerHTML = "<p>Loading…</p>";
    await renderPanel(p);
  }
  const pct = (x, d = 2) => (x == null ? "n/a" : (100 * x).toFixed(d) + "%");
  const num = (x) => (x == null ? "n/a" : x.toLocaleString());
  function spark(title, arr, fmt) {
    const v = arr.map((x) => (x == null ? null : x));
    const ok = v.filter((x) => x != null);
    if (ok.length < 2) return `<div class="spark"><div class="t"><span>${title}</span><span>n/a</span></div></div>`;
    const lo = Math.min(...ok), hi = Math.max(...ok), span = hi - lo || 1;
    const W = 300, H = 34, n = v.length;
    const pts = v.map((x, i) => (x == null ? null : [(i / (n - 1)) * W, H - 4 - ((x - lo) / span) * (H - 8)]));
    let d = "", pen = false;
    pts.forEach((q) => { if (!q) { pen = false; return; } d += (pen ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); pen = true; });
    const cur = pts[idx];
    return `<div class="spark"><div class="t"><span>${title}</span><span>${fmt(v[idx])} <span class="note">(range ${fmt(lo)} to ${fmt(hi)})</span></span></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${title} over time"><path d="${d}" fill="none" stroke="var(--accent)" stroke-width="1.6"/>
      ${cur ? `<circle cx="${cur[0]}" cy="${cur[1]}" r="3.2" fill="#d7301f"/>` : ""}</svg></div>`;
  }
  async function renderPanel(p) {
    const f = await getFacts(p.b);
    if (current !== p) return;
    const heightFt = Math.round(p.h / 0.3048);
    const head = `<h2>Building lot ${p.b}</h2><div class="meta">${p.bo === "BK" ? "Brooklyn" : "Bronx"} · community district ${p.cd} · ${p.u} units · ${p.yb ? "built " + p.yb : "year built unknown"} · ${heightFt} ft tall${f ? " · class " + f.cls : ""}</div>`;
    if (!f) { $("panel-body").innerHTML = head + "<p>No detail record for this building.</p>"; return; }
    const g = f.gap[idx];
    const gapText = g == null ? "n/a" : `${g.toFixed(2)} (${g > 0.15 ? "quieter than predicted condition suggests" : g < -0.15 ? "louder than predicted condition suggests" : "about as loud as predicted"})`;
    $("panel-body").innerHTML = head + `
      <h3>Model estimates · ${snaps[idx]}</h3>
      <table class="facts">
        <tr><td>Predicted risk of an enforcement event, next 12 months</td><td>${pct(f.risk[idx])}</td></tr>
        <tr><td>Predicted condition (no complaint information)</td><td>${pct(f.cond[idx], 3)}</td></tr>
        <tr><td>Complaint gap (within-borough rank difference)</td><td>${gapText}</td></tr>
        <tr><td>In the top 10% of the gap in its borough</td><td>${f.silent[idx] ? "yes" : "no"}</td></tr>
        <tr><td>Share of closed complaints with no access</td><td>${f.nacc[idx] == null ? "none closed" : pct(f.nacc[idx], 0)}${f.blocked[idx] ? " (access-blocked)" : ""}</td></tr>
      </table>
      <h3>Public record counts · ${snaps[idx]}</h3>
      <table class="facts">
        <tr><td>HPD violations still open</td><td>${num(f.open_viol[idx])}</td></tr>
        <tr><td>HPD violations issued, last 12 months (class C)</td><td>${num(f.viol12[idx])} (${num(f.viol_c12[idx])})</td></tr>
        <tr><td>HPD complaint problems, last 12 months</td><td>${num(f.complaints12[idx])}</td></tr>
        <tr><td>311 housing requests, last 12 months</td><td>${num(f.c311_12[idx])}</td></tr>
        <tr><td>Evictions executed, last 12 months</td><td>${num(f.evict12[idx])}</td></tr>
        <tr><td>DOB violations, last 12 months</td><td>${num(f.dob12[idx])}</td></tr>
        <tr><td>Earlier emergency-repair charges (OMO)</td><td>${num(f.omo_prior[idx])}</td></tr>
        <tr><td>Earlier HPD litigations</td><td>${num(f.litig_prior[idx])}</td></tr>
        <tr><td>Earlier vacate orders / AEP selections</td><td>${num(f.vacate_prior[idx])} / ${num(f.aep_prior[idx])}</td></tr>
      </table>
      <h3>Over time (red dot = selected snapshot)</h3>
      ${spark("Predicted risk", f.risk, (x) => pct(x, 1))}
      ${spark("Predicted condition", f.cond, (x) => pct(x, 2))}
      ${spark("Complaints per unit (12 months)", f.complaints_pu, (x) => (x == null ? "n/a" : x.toFixed(2)))}
      ${spark("Open HPD violations", f.open_viol, num)}
      <div class="disc">Model estimates for research, not findings about this building's owner or tenants. Many individual predictions are wrong. Counts are from public NYC records and are only as complete as those records.</div>`;
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    $("layer").addEventListener("change", (e) => { layerKey = e.target.value; applyStyle(); });
    $("slider").addEventListener("input", (e) => { idx = +e.target.value; applyStyle(); });
    ["borough", "district", "only-gap", "only-access"].forEach((id) => $(id).addEventListener("change", () => {
      if (id === "borough" && $("district").value && districtById[$("district").value] && $("borough").value && districtById[$("district").value].bo !== $("borough").value) $("district").value = "";
      applyStyle();
    }));
    $("district").addEventListener("change", (e) => { if (e.target.value) focusDistrict(e.target.value); });
    $("help-btn").addEventListener("click", () => { const h = $("help"); h.hidden = !h.hidden; $("help-btn").setAttribute("aria-expanded", String(!h.hidden)); });
    $("play").addEventListener("click", () => {
      if (timer) { clearInterval(timer); timer = null; $("play").innerHTML = "&#9654;"; return; }
      $("play").innerHTML = "&#10074;&#10074;";
      timer = setInterval(() => { idx = (idx + 1) % snaps.length; applyStyle(); }, 900);
    });
    $("theme").addEventListener("click", () => setTheme(theme() === "dark" ? "light" : "dark"));
    $("tilt").addEventListener("click", () => map.easeTo({ center: mode === "sample" ? map.getCenter() : [-73.915, 40.7], zoom: mode === "sample" ? 14.2 : 10.4, pitch: 52, bearing: -18, duration: 800 }));
    $("panel-close").addEventListener("click", () => { $("panel").hidden = true; current = null; setSelected(""); });
    const about = () => { $("modal").hidden = false; $("modal-ok").focus(); };
    $("about").addEventListener("click", about);
    $("foot-about").addEventListener("click", (e) => { e.preventDefault(); about(); });
    $("modal-ok").addEventListener("click", () => { $("modal").hidden = true; store.set("cgm-seen", "1"); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("modal").hidden = true; if (!$("panel").hidden) { $("panel").hidden = true; current = null; setSelected(""); } } });
    if (!store.get("cgm-seen")) $("modal").hidden = false;
  }

  wire();
  init().catch((e) => { console.error(e); $("legend").textContent = "Could not load map data: " + e.message; });
  window.__cgm = { get map() { return map; }, set: (k, i) => { if (k) layerKey = k; if (i != null) idx = i; $("layer").value = layerKey; applyStyle(); }, open: openPanel };
})();
