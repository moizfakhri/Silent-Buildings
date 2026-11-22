/* NYC Housing Monitor — 3D Civic Atlas, Building Report Cards, Investigations & District Rankings.
   Static client-side app (MapLibre GL + PMTiles, zero build step, works offline with graceful basemap fallback). */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------------------------ Color scales & 8 Atlas Layers
  const NULLCOL = "#8b929c";
  const RAMP_HEAT = [[0, "#e9e5db"], [1, "#f7dcb4"], [2, "#f4b96b"], [4, "#e67b3c"], [6, "#c43927"], [7, "#6e0e0e"]];
  const RAMP_SEQ = [[0, "#ebe7dd"], [1, "#f8d8ad"], [280, "#f29d5b"], [620, "#d1432a"], [998, "#6e0e0e"]];
  const RAMP_OMO = [[0, "#ebe7dd"], [1, "#f7e3b5"], [350, "#e5a336"], [700, "#c8561d"], [998, "#68160c"]];
  const RAMP_PORT = [[0, "#d8e6f0"], [250, "#9abbd6"], [550, "#e6a34c"], [800, "#d14a2a"], [998, "#751212"]];
  const RAMP_EVICT = [[0, "#ebe7dd"], [1, "#f5d0d5"], [350, "#dc7283"], [700, "#a8243a"], [998, "#560a1b"]];
  const RAMP_BLUE = [[0, "#edf2f7"], [250, "#b8d0e8"], [500, "#689ed4"], [750, "#245d99"], [998, "#0d2b52"]];
  const RAMP_DIV = [[0, "#215c96"], [250, "#8ebbd9"], [499, "#eceae4"], [750, "#eba07c"], [998, "#b01f2b"]];

  const LAYERS = {
    heat: {
      group: "Investigations (2018–2025)",
      label: "7-Winter Heat & Hot Water Recidivism",
      kind: "static", prop: "hw", max: 7, ramp: RAMP_HEAT, dKey: "heat7_n", dFmt: (x) => `${x} buildings`,
      lo: "0 winters", hi: "7 of 7 winters", unit: "winters with 3+ heat/hot-water complaints (2018–2025)",
      help: "Counts how many of the last 7 winters (2018–19 through 2024–25) the building logged 3+ HPD heat or hot-water complaints. Just 1,766 buildings (1.7%) failed all 7 winters and generated 48.2% of all winter heat emergencies across Bronx & Brooklyn. Buildings with 6/6 prior failed winters fail again 92.0% of the time.",
    },
    omo: {
      group: "Investigations (2018–2025)",
      label: "Taxpayer Emergency Repair Spend (OMO $)",
      kind: "static", prop: "om", max: 998, ramp: RAMP_OMO, dKey: "omo_m", dFmt: (x) => `$${x.toFixed(1)}M`,
      lo: "$0", hi: "$150k+ (log scale)", unit: "HPD Open Market Order emergency repair awards (2018+)",
      help: "Public dollars awarded by HPD to private contractors for emergency repairs (demolition, construction, lead abatement, plumbing, heat) when owners fail to act. The top 1% of buildings account for 50.4% of all taxpayer OMO dollars ($196.1M in this 3+ unit spine since 2018).",
    },
    openc: {
      group: "Investigations (2018–2025)",
      label: "Open 'Zombie' Class C Hazards",
      kind: "static", prop: "oc", max: 998, ramp: RAMP_SEQ, dKey: "open_c_pu", dFmt: (x) => `${x.toFixed(2)} / unit`,
      lo: "0 open", hi: "2+ open/unit", unit: "unresolved Class C immediately hazardous violations per unit",
      help: "Class C ('Immediately Hazardous') violations legally require correction within 24 hours (21 days for lead). Across 1.06M Class C violations since 2018, Kaplan-Meier median closure time is 110 days—and 590 days for Mold, 265 for Pests, and 256 for Lead Paint.",
    },
    port: {
      group: "Investigations (2018–2025)",
      label: "Landlord Portfolio Contagion (Sister Rate)",
      kind: "static", prop: "pt", max: 998, ramp: RAMP_PORT, dKey: "sis_avg", dFmt: (x) => `${x.toFixed(2)} C/unit`,
      lo: "sisters clean (0)", hi: "sisters severe", unit: "leave-one-out Class C/unit across owner's other buildings (grey = single-bldg/unlinked)",
      help: "Anonymized leave-one-out Class C violation rate per unit across OTHER buildings linked to the same HPD registration business address (2–200 building portfolios, zero personal names stored). Among completely quiet buildings (0 complaints & 0 violations), sister-building distress triples next-year Class C risk (OR 1.35, p < 1e-34).",
    },
    evict: {
      group: "Investigations (2018–2025)",
      label: "Marshal Evictions Rate (2018–2025)",
      kind: "static", prop: "ev", max: 998, ramp: RAMP_EVICT, dKey: "ev_p1k", dFmt: (x) => `${x.toFixed(1)} / 1k units`,
      lo: "0 evictions", hi: "35+ per 100 units", unit: "executed residential marshal evictions per 100 units",
      help: "Post-moratorium (2022–2025), 80.9% of executed marshal evictions occurred inside buildings with at least 1 open Class C hazard (60.9% with 5+). Even matched to identical-size same-neighborhood buildings, evicting buildings have 1.95x more Class C hazards/unit and 2.11x more harassment litigations.",
    },
    risk: {
      group: "Quarterly Out-of-Time Models (2022–2025)",
      label: "Enforcement Risk Forecast (Quarterly)",
      kind: "series", key: "r", ramp: RAMP_SEQ, dKey: "risk", dFmt: (x) => `${(100 * x).toFixed(1)}% avg`,
      lo: "lower risk", hi: "higher risk", unit: "walk-forward LightGBM percentile within snapshot",
      help: "Out-of-time probability of a vacate order, OMO charge, AEP selection, or HPD litigation in the next 12 months (trained strictly on earlier quarters with a 12-month purge gap; PR-AUC 0.645 vs 0.558 rule baseline). Largely reflects active city engagement.",
    },
    gap: {
      group: "Quarterly Out-of-Time Models (2022–2025)",
      label: "Complaint Gap Diagnostic (Phase 4)",
      kind: "series", key: "g", ramp: RAMP_DIV, dKey: "gap", dFmt: (x) => `${x > 0 ? "+" : ""}${x.toFixed(2)}`,
      lo: "louder than predicted", hi: "quieter than predicted", unit: "predicted condition rank minus complaint loudness rank",
      help: "Original Phase 4 diagnostic comparing complaint-blind predicted condition to observed complaints per unit. Validation showed silent buildings alone did NOT have hidden extra risk (observed/predicted 0.84; matched RR 0.65)—unlike portfolio sister distress, which strongly predicts future Class C hazards.",
    },
    access: {
      group: "Quarterly Out-of-Time Models (2022–2025)",
      label: "Inspector No-Access Rate (Quarterly)",
      kind: "series", key: "a", ramp: RAMP_BLUE, dKey: "nacc", dFmt: (x) => `${(100 * x).toFixed(0)}% avg`,
      lo: "0%", hi: "100%", unit: "share of closed problems ending with no inspector access (12m)",
      help: "About 15–16% of closed HPD complaint problems end with the inspector unable to gain access (median 18 days to close vs 4 days when accessed). Access-blocked buildings did not show extra later vacate/DOB risk.",
    },
  };

  const PRESETS = {
    heat7: { layer: "heat", label: "6–7 winter heat repeaters", filter: [">=", ["get", "hw"], 6] },
    omo50: { layer: "omo", label: "OMO spend $50k+", filter: [">=", ["get", "omk"], 50] },
    contagion: { layer: "port", label: "Quiet buildings in distressed portfolios", filter: ["==", ["get", "qp"], 1] },
    evhaz: { layer: "evict", label: "Evicting + 5+ open Class C hazards", filter: ["==", ["get", "eh"], 1] },
    access: { layer: "access", label: "Access-blocked buildings", filter: () => ["==", ["slice", ["get", "ab"], idx, idx + 1], "1"] },
  };

  // ------------------------------------------------------------------ State
  let map = null, meta = null, snaps = [], idx = 15, layerKey = "heat", mode = "tiles";
  let districts = null, digest = null, sampleGeo = null, sampleFacts = null, sampleSearch = null;
  let sampleCenter = [-73.915, 40.705];
  let activePreset = null, basemapOn = true, districtView = false, selectedBbl = "", currentProps = null, playTimer = null;
  const districtById = {}, factsCache = {}, searchCache = {};
  let rankSort = { col: "omo_m", dir: -1 }, rankBoro = "";
  const DISTRICT_ZOOM = 12.2;
  const dscale = {};

  // ------------------------------------------------------------------ Theme (modern-web-guidance: dark-mode-toggle)
  const metaCS = document.querySelector('meta[name="color-scheme"]');
  const sysDark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const renderedTheme = () => {
    const c = metaCS ? metaCS.content : "light dark";
    if (c === "dark" || c === "light") return c;
    return sysDark() ? "dark" : "light";
  };
  function syncThemeToMap() {
    const dark = renderedTheme() === "dark";
    $("theme-btn").setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    if (!map || !map.isStyleLoaded()) return;
    map.setPaintProperty("bg", "background-color", dark ? "#0d1117" : "#ede8dc");
    if (map.getLayer("context")) map.setPaintProperty("context", "fill-extrusion-color", dark ? "#232a36" : "#cfc9bc");
    if (map.getLayer("districts-line")) map.setPaintProperty("districts-line", "line-color", dark ? "#8e9bb0" : "#515a69");
    if (map.getLayer("basemap-light")) map.setLayoutProperty("basemap-light", "visibility", basemapOn && !dark ? "visible" : "none");
    if (map.getLayer("basemap-light-ref")) map.setLayoutProperty("basemap-light-ref", "visibility", basemapOn && !dark ? "visible" : "none");
    if (map.getLayer("basemap-dark")) map.setLayoutProperty("basemap-dark", "visibility", basemapOn && dark ? "visible" : "none");
    if (map.getLayer("basemap-dark-ref")) map.setLayoutProperty("basemap-dark-ref", "visibility", basemapOn && dark ? "visible" : "none");
  }
  function toggleTheme() {
    const target = renderedTheme() === "dark" ? "light" : "dark";
    const sys = sysDark() ? "dark" : "light";
    if (target === sys) {
      try { localStorage.removeItem("color-scheme"); } catch (e) {}
      if (metaCS) metaCS.content = "light dark";
    } else {
      try { localStorage.setItem("color-scheme", target); } catch (e) {}
      if (metaCS) metaCS.content = target;
    }
    syncThemeToMap();
  }
  window.addEventListener("storage", (e) => {
    if (e.key === "color-scheme" && metaCS) {
      metaCS.content = e.newValue === "light" || e.newValue === "dark" ? e.newValue : "light dark";
      syncThemeToMap();
    }
  });
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", syncThemeToMap);
  }

  // ------------------------------------------------------------------ Map Styling Expressions
  const seriesVal = (key, i) => ["to-number", ["slice", ["get", key], i * 3, i * 3 + 3], 999];
  function buildingColorExpr(L, i) {
    const stops = [];
    L.ramp.forEach(([s, c]) => stops.push(s, c));
    if (L.kind === "series") {
      return ["case", ["==", seriesVal(L.key, i), 999], NULLCOL, ["interpolate", ["linear"], seriesVal(L.key, i), ...stops]];
    }
    return ["case", ["==", ["get", L.prop], 999], NULLCOL, ["interpolate", ["linear"], ["get", L.prop], ...stops]];
  }
  function districtColorExpr(L, i) {
    const stops = [];
    const maxS = L.max || 998;
    L.ramp.forEach(([s, c]) => stops.push(Math.round((s / maxS) * 998), c));
    const prop = "_d_" + layerKey;
    if (L.kind === "series") {
      return ["case", ["==", seriesVal(prop, i), 999], NULLCOL, ["interpolate", ["linear"], seriesVal(prop, i), ...stops]];
    }
    return ["case", ["==", ["get", prop], 999], NULLCOL, ["interpolate", ["linear"], ["get", prop], ...stops]];
  }
  function buildDistrictScales() {
    Object.entries(LAYERS).forEach(([lk, L]) => {
      const prop = "_d_" + lk;
      if (L.kind === "series") {
        const all = [];
        districts.features.forEach((f) => (f.properties.v[L.dKey] || []).forEach((x) => { if (x != null) all.push(x); }));
        let lo = Math.min(...all), hi = Math.max(...all);
        if (lk === "gap") { hi = Math.max(Math.abs(lo), Math.abs(hi)); lo = -hi; }
        dscale[lk] = [lo, hi];
        districts.features.forEach((f) => {
          f.properties[prop] = (f.properties.v[L.dKey] || []).map((x) =>
            String(x == null ? 999 : Math.max(0, Math.min(998, Math.round(((x - lo) / (hi - lo || 1)) * 998)))).padStart(3, "0")
          ).join("");
        });
      } else {
        const all = districts.features.map((f) => f.properties.s && f.properties.s[L.dKey]).filter((x) => x != null);
        const lo = Math.min(...all), hi = Math.max(...all);
        dscale[lk] = [lo, hi];
        districts.features.forEach((f) => {
          const x = f.properties.s ? f.properties.s[L.dKey] : null;
          f.properties[prop] = x == null ? 999 : Math.max(0, Math.min(998, Math.round(((x - lo) / (hi - lo || 1)) * 998)));
        });
      }
    });
  }

  function activeFilterExpr() {
    const f = ["all"];
    const b = $("borough").value, d = $("district").value;
    if (b) f.push(["==", ["get", "bo"], b]);
    if (d) f.push(["==", ["get", "cd"], d]);
    if (activePreset && PRESETS[activePreset]) {
      const pf = PRESETS[activePreset].filter;
      f.push(typeof pf === "function" ? pf() : pf);
    }
    return f.length > 1 ? f : null;
  }

  function renderLegend() {
    const L = LAYERS[layerKey];
    const maxS = L.max || 998;
    const grad = L.ramp.map(([s, c]) => `${c} ${(s / maxS) * 100}%`).join(", ");
    const dv = districtView && dscale[layerKey];
    const lo = dv ? L.dFmt(dscale[layerKey][0]) : L.lo;
    const hi = dv ? L.dFmt(dscale[layerKey][1]) : L.hi;
    const unit = dv ? "Neighborhood district summary — zoom in for 3D buildings" : L.unit;
    $("legend").innerHTML = `<div class="ramp" style="background:linear-gradient(90deg, ${grad})"></div>
      <div class="ramp-labels"><span>${esc(lo)}</span><span>${esc(hi)}</span></div>
      <div class="muted" style="margin-top:3px">${esc(unit)} · <span class="swatch" style="background:${NULLCOL}"></span>n/a</div>`;
    $("layer-help").textContent = L.help;
  }

  function applyStyle() {
    const L = LAYERS[layerKey];
    $("timebar").hidden = L.kind !== "series";
    if (L.kind !== "series" && playTimer) stopPlayback();

    if (map && map.getLayer("scored")) {
      map.setPaintProperty("scored", "fill-extrusion-color", buildingColorExpr(L, idx));
      map.setFilter("scored", activeFilterExpr());
    }
    if (map && map.getLayer("districts-fill")) {
      map.setPaintProperty("districts-fill", "fill-color", districtColorExpr(L, idx));
      const b = $("borough").value;
      map.setFilter("districts-fill", b ? ["==", ["get", "bo"], b] : null);
      map.setFilter("districts-line", b ? ["==", ["get", "bo"], b] : null);
    }
    document.querySelectorAll(".preset-chip").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.preset === activePreset);
    });
    const hasFilter = Boolean($("borough").value || $("district").value || activePreset);
    $("clear-filters").hidden = !hasFilter;

    const parts = [];
    if (activePreset) parts.push(PRESETS[activePreset].label);
    if ($("district").value && districtById[$("district").value]) parts.push(districtById[$("district").value].nm);
    else if ($("borough").value) parts.push($("borough").value === "BX" ? "Bronx" : "Brooklyn");
    $("filter-status").textContent = parts.length ? "Active: " + parts.join(" · ") : "Showing all 101,442 scored residential lots";

    if (snaps[idx]) $("snap-label").textContent = snaps[idx];
    $("slider").value = idx;
    renderLegend();
    writeHash();
    if (!$("panel").hidden && currentProps) renderPanel(currentProps);
  }

  // ------------------------------------------------------------------ URL Hash
  function readHash() {
    const h = new URLSearchParams(location.hash.slice(1)), out = {};
    if (LAYERS[h.get("l")]) out.layer = h.get("l");
    if (h.get("s") && /^\d+$/.test(h.get("s"))) out.idx = +h.get("s");
    if (h.get("p") && PRESETS[h.get("p")]) out.preset = h.get("p");
    if (["map", "studies", "districts"].includes(h.get("tab"))) out.tab = h.get("tab");
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
      const activeTab = document.querySelector('.nav-tabs [aria-selected="true"]')?.dataset.view || "map";
      const pStr = activePreset ? `&p=${activePreset}` : "";
      const tStr = activeTab !== "map" ? `&tab=${activeTab}` : "";
      try { history.replaceState(null, "", `${location.pathname}${location.search}#l=${layerKey}&s=${idx}${pStr}${tStr}&v=${v}`); } catch (e) {}
    }, 250);
  }

  function setSelected(bbl) {
    selectedBbl = bbl || "";
    if (map && map.getLayer("selected")) map.setFilter("selected", ["==", ["get", "b"], selectedBbl]);
  }

  // ------------------------------------------------------------------ Viewport-Clamped Hover Tooltip
  function positionTooltip(pt) {
    const h = $("hover");
    const cont = $("view-map").getBoundingClientRect();
    h.hidden = false;
    const hw = h.offsetWidth || 240, hh = h.offsetHeight || 70;
    const panelOpen = !$("panel").hidden;
    const maxX = cont.width - (panelOpen ? 410 : 14) - hw;
    const maxY = cont.height - 36 - hh;
    const x = Math.max(12, Math.min(pt.x + 14, maxX));
    const y = Math.max(12, Math.min(pt.y + 14, maxY));
    h.style.left = x + "px";
    h.style.top = y + "px";
  }

  function hoverDistrict(e) {
    const p = districtById[e.features[0].properties.cd];
    if (!p) return;
    const L = LAYERS[layerKey];
    let valTxt = "n/a";
    if (L.kind === "series") {
      const ser = p.v && p.v[L.dKey];
      const x = ser ? ser[idx] : null;
      if (x != null) valTxt = L.dFmt(x);
    } else if (p.s && p.s[L.dKey] != null) {
      valTxt = L.dFmt(p.s[L.dKey]);
    }
    $("hover").innerHTML = `<strong>${esc(p.nm)}</strong> <span class="muted">(${p.bo} ${p.cd})</span><br>
      ${p.n.toLocaleString()} buildings · ${p.s.units.toLocaleString()} units<br>
      ${esc(L.label)}: <strong>${esc(valTxt)}</strong><br>
      <span class="muted">Click to zoom into neighborhood</span>`;
    positionTooltip(e.point);
    map.getCanvas().style.cursor = "pointer";
  }

  function hoverBuilding(e) {
    const p = e.features[0].properties;
    const addr = p.ad || `Lot ${p.b}`;
    let line2 = `${p.u} units · ${p.yb ? "built " + p.yb : "year n/a"}`;
    if (layerKey === "heat") line2 = `<strong>${p.hw}/7</strong> failed winters · ${p.u} units`;
    else if (layerKey === "omo") line2 = `OMO spend: <strong>$${(p.omk || 0).toLocaleString()}k</strong> · ${p.u} units`;
    else if (layerKey === "openc") line2 = `<strong>${p.ocn || 0}</strong> open Class C hazards · ${p.u} units`;
    else if (layerKey === "evict") line2 = `<strong>${p.evn || 0}</strong> evictions (2018–25) · ${p.u} units`;
    else if (layerKey === "port") line2 = p.pt === 999 ? `Single-building or unlinked · ${p.u} units` : `Multi-building portfolio · ${p.u} units`;
    $("hover").innerHTML = `<strong>${esc(addr)}</strong><br>${line2}<br><span class="muted">Click for Building Report Card</span>`;
    positionTooltip(e.point);
    map.getCanvas().style.cursor = "pointer";
  }

  function bboxOf(geom) {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    const walk = (c) => {
      if (typeof c[0] === "number") { x0 = Math.min(x0, c[0]); x1 = Math.max(x1, c[0]); y0 = Math.min(y0, c[1]); y1 = Math.max(y1, c[1]); }
      else c.forEach(walk);
    };
    walk(geom.coordinates);
    return [[x0, y0], [x1, y1]];
  }

  // Smooth zoom to district WITHOUT trapping user in a hard filter unless chosen from dropdown
  function flyToDistrict(cd, applyFilter = false) {
    const f = districts && districts.features.find((x) => x.properties.cd === cd);
    if (applyFilter) $("district").value = cd;
    if (f && map) map.fitBounds(bboxOf(f.geometry), { padding: 60, pitch: 54, maxZoom: 14.5, duration: 900 });
    applyStyle();
  }

  // ------------------------------------------------------------------ Building Report Card
  async function getFacts(bbl) {
    if (mode === "sample") {
      if (!sampleFacts) sampleFacts = await (await fetch("data/sample/facts.json")).json();
      return sampleFacts[bbl];
    }
    const k = bbl.slice(0, 5);
    if (!factsCache[k]) {
      try { factsCache[k] = await (await fetch(`data/facts/${k}.json`)).json(); } catch (e) { factsCache[k] = {}; }
    }
    return factsCache[k][bbl];
  }

  async function openPanel(p) {
    currentProps = p;
    setSelected(p.b);
    $("panel").hidden = false;
    $("panel-body").innerHTML = '<p class="muted">Loading Building Report Card…</p>';
    await renderPanel(p);
  }

  const pct = (x, d = 1) => (x == null ? "n/a" : (100 * x).toFixed(d) + "%");
  const num = (x) => (x == null ? "n/a" : x.toLocaleString());
  const usd = (x) => (x == null || x === 0 ? "$0" : x >= 1e6 ? "$" + (x / 1e6).toFixed(2) + "M" : "$" + x.toLocaleString());

  function spark(title, arr, fmt) {
    const v = (arr || []).map((x) => (x == null ? null : x));
    const ok = v.filter((x) => x != null);
    if (ok.length < 2) return `<div class="spark"><div class="t"><span>${esc(title)}</span><span class="muted">n/a</span></div></div>`;
    const lo = Math.min(...ok), hi = Math.max(...ok), span = hi - lo || 1;
    const W = 330, H = 32, n = v.length;
    const pts = v.map((x, i) => (x == null ? null : [(i / (n - 1)) * W, H - 4 - ((x - lo) / span) * (H - 8)]));
    let d = "", pen = false;
    pts.forEach((q) => { if (!q) { pen = false; return; } d += (pen ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); pen = true; });
    const cur = pts[idx];
    return `<div class="spark"><div class="t"><span>${esc(title)}</span><span><strong>${esc(fmt(v[idx]))}</strong> <span class="muted">(${esc(fmt(lo))}–${esc(fmt(hi))})</span></span></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(title)} over time">
        <path d="${d}" fill="none" stroke="var(--slate)" stroke-width="1.8"/>
        ${cur ? `<circle cx="${cur[0]}" cy="${cur[1]}" r="3.4" fill="var(--signal)"/>` : ""}
      </svg></div>`;
  }

  async function renderPanel(p) {
    const f = await getFacts(p.b);
    if (currentProps !== p) return;
    const heightFt = p.h ? Math.round(p.h / 0.3048) : null;
    const addr = (f && f.addr) || p.ad || `Building lot ${p.b}`;
    const cdLbl = (f && f.cd_lbl) || (districtById[p.cd] && districtById[p.cd].nm) || `District ${p.cd}`;
    const boName = (f ? f.bo : p.bo) === "BX" ? "Bronx" : "Brooklyn";
    const boCode = (f ? f.bo : p.bo);

    const regLabels = {
      active_corp: ["Active Corporate / LLC", "badge-slate"],
      active_indiv: ["Active Individual", "badge-teal"],
      expired: ["Expired HPD Registration", "badge-red"],
      unregistered: ["No HPD Registration", "badge-amber"],
      active_other: ["Active Registration", "badge-slate"],
    };
    const [regTxt, regCls] = f ? (regLabels[f.reg_st] || ["Registered", "badge-slate"]) : ["", "badge-slate"];

    const head = `
      <div class="rc-eyebrow">
        <span class="roundel ${boCode === "BX" ? "roundel-bx" : "roundel-bk"}" style="width:20px;height:20px;font-size:9px">${boCode}</span>
        <span>${esc(cdLbl)} · BBL ${esc(p.b)}</span>
      </div>
      <h2 class="rc-title">${esc(addr)}</h2>
      <div class="rc-sub">
        ${f ? f.u : p.u} units · ${(f && f.yb) || p.yb ? "built " + ((f && f.yb) || p.yb) : "year unknown"}${heightFt ? ` · ${heightFt} ft` : ""}${f ? ` · Class ${esc(f.cls)}` : ""}
      </div>
      ${regTxt ? `<span class="badge ${regCls}">${esc(regTxt)}</span>` : ""}
      ${f && f.aep_tot > 0 ? ` <span class="badge badge-red">AEP Selected (${f.aep_tot}×)</span>` : ""}`;

    if (!f) {
      $("panel-body").innerHTML = head + '<p class="muted" style="margin-top:12px">No detail record available for this lot.</p>';
      return;
    }

    const openAge = f.open_c > 0 && f.open_c_med_d != null
      ? (f.open_c_med_d >= 365 ? `median ${(f.open_c_med_d / 365).toFixed(1)} yrs open` : `median ${f.open_c_med_d}d open`)
      : "none currently open";
    const kpiStrip = `
      <div class="rc-kpis">
        <div class="rc-kpi ${f.open_c >= 5 ? "kpi-hot" : f.open_c >= 1 ? "kpi-warn" : ""}">
          <div class="k-lbl">Open Class C</div>
          <div class="k-val">${num(f.open_c)}</div>
          <div class="k-sub">${esc(openAge)}</div>
        </div>
        <div class="rc-kpi ${f.omo_usd >= 50000 ? "kpi-hot" : f.omo_usd >= 5000 ? "kpi-warn" : ""}">
          <div class="k-lbl">Taxpayer OMO Spend</div>
          <div class="k-val">${esc(usd(f.omo_usd))}</div>
          <div class="k-sub">${num(f.omo_n)} emergency orders</div>
        </div>
        <div class="rc-kpi ${f.hw_w >= 6 ? "kpi-hot" : f.hw_w >= 3 ? "kpi-warn" : ""}">
          <div class="k-lbl">Winter Heat Record</div>
          <div class="k-val">${f.hw_w} / 7</div>
          <div class="k-sub">${num(f.hw_tot)} complaints (7 winters)</div>
        </div>
        <div class="rc-kpi ${f.ev_tot >= 3 ? "kpi-hot" : f.ev_tot >= 1 ? "kpi-warn" : ""}">
          <div class="k-lbl">Marshal Evictions</div>
          <div class="k-val">${num(f.ev_tot)}</div>
          <div class="k-sub">executed 2018–2025</div>
        </div>
      </div>`;

    // Peer comparison bar
    const peerHtml = `
      <div class="rc-section">
        <h3>Same-Size ${boName} Peer Comparison</h3>
        <div style="display:flex;justify-content:space-between;font-size:12px">
          <span>Open Class C hazards per unit</span>
          <strong style="font-family:var(--font-mono)">${f.open_c > 0 ? `Higher than ${f.peer_pct}% of peers` : "0 open (cleanest tier)"}</strong>
        </div>
        <div class="peer-bar-track"><div class="peer-bar-fill" style="width:${f.open_c > 0 ? Math.max(4, f.peer_pct) : 0}%"></div></div>
      </div>`;

    // Anonymized Landlord Portfolio Contagion Box
    let portHtml = "";
    if (f.p_bldgs >= 2 && f.p_sis_c != null) {
      const hot = f.p_sis_c >= 0.15;
      const isQuiet = (f.viol12[15] || 0) === 0 && (f.complaints12[15] || 0) === 0;
      portHtml = `
        <div class="rc-section">
          <h3>Anonymized Portfolio Context</h3>
          <div class="port-box ${hot ? "port-hot" : ""}">
            Linked to a <strong>${num(f.p_bldgs)}-building portfolio</strong> (${num(f.p_units)} total units).
            Sister buildings average <strong>${f.p_sis_c.toFixed(2)} Class C hazards/unit</strong> (2022–25).
            ${isQuiet && hot ? '<div style="margin-top:5px;font-weight:600;color:var(--signal)">Quiet-building contagion signal: this building had 0 recent complaints/violations, but sister buildings show elevated Class C distress.</div>' : ""}
          </div>
        </div>`;
    } else if (f.p_bldgs === 1) {
      portHtml = `
        <div class="rc-section">
          <h3>Anonymized Portfolio Context</h3>
          <div class="port-box">Single-building HPD registration address (no linked sister buildings in Bronx/Brooklyn).</div>
        </div>`;
    }

    // Hazard category breakdown bars
    const hazLabels = {
      heat: "Heat & Hot Water", pests: "Pests / Rodents", lead: "Lead Paint",
      mold: "Mold / Mildew", water: "Water / Plumbing", fire: "Fire / Smoke / CO",
      doors: "Doors / Locks", walls: "Plaster / Walls",
    };
    const hazEntries = Object.entries(f.haz || {}).sort((a, b) => b[1] - a[1]);
    let hazHtml = "";
    if (hazEntries.length) {
      const maxH = hazEntries[0][1] || 1;
      hazHtml = `
        <div class="rc-section">
          <h3>Class C Hazards by Category (2018–2025)</h3>
          ${hazEntries.map(([k, v]) => `
            <div class="haz-row">
              <span>${esc(hazLabels[k] || k)}</span>
              <div class="haz-track"><div class="haz-fill" style="width:${Math.max(4, Math.round((v / maxH) * 100))}%"></div></div>
              <span class="haz-num">${num(v)}</span>
            </div>`).join("")}
        </div>`;
    }

    // Quarterly sparklines
    const sparkHtml = `
      <div class="rc-section">
        <h3>Quarterly Trajectory (Red dot = ${snaps[idx]})</h3>
        ${spark("Open HPD violations", f.open_viol, num)}
        ${spark("Complaints per unit (12m)", f.complaints_pu, (x) => (x == null ? "n/a" : x.toFixed(2)))}
        ${spark("Predicted enforcement risk", f.risk, (x) => pct(x, 1))}
      </div>`;

    // Collapsible full record table & caveats
    const detailsHtml = `
      <details class="rc-details">
        <summary>Full snapshot counts (${snaps[idx]}) &amp; model diagnostics</summary>
        <table class="facts">
          <tr><td>Predicted risk (next 12m)</td><td>${pct(f.risk[idx], 1)}</td></tr>
          <tr><td>Predicted condition (no complaints)</td><td>${pct(f.cond[idx], 2)}</td></tr>
          <tr><td>Complaint gap rank diff</td><td>${f.gap[idx] == null ? "n/a" : f.gap[idx].toFixed(2)}</td></tr>
          <tr><td>No-access share (closed 12m)</td><td>${f.nacc[idx] == null ? "none closed" : pct(f.nacc[idx], 0)}</td></tr>
          <tr><td>HPD violations issued (12m / Class C)</td><td>${num(f.viol12[idx])} / ${num(f.viol_c12[idx])}</td></tr>
          <tr><td>HPD complaints / 311 requests (12m)</td><td>${num(f.complaints12[idx])} / ${num(f.c311_12[idx])}</td></tr>
          <tr><td>DOB violations (12m)</td><td>${num(f.dob12[idx])}</td></tr>
          <tr><td>Prior OMO / Litigations / Vacates</td><td>${num(f.omo_prior[idx])} / ${num(f.litig_prior[idx])} / ${num(f.vacate_prior[idx])}</td></tr>
        </table>
        <p class="muted" style="margin:8px 0 0">Public NYC Open Data counts &amp; research model estimates. Zero personal owner or tenant names are stored.</p>
      </details>`;

    $("panel-body").innerHTML = head + kpiStrip + peerHtml + portHtml + hazHtml + sparkHtml + detailsHtml;
  }

  // ------------------------------------------------------------------ Sharded Street Address / BBL / District Search
  function shardKeyForQuery(q) {
    const tokens = (q.toUpperCase().match(/[A-Z0-9]+/g) || []);
    const street = tokens.find((t) => /[A-Z]/.test(t)) || tokens[0] || "";
    if (street.length < 2) return null;
    return street.slice(0, 2);
  }
  async function loadSearchShard(key) {
    if (mode === "sample") {
      if (!sampleSearch) {
        try { sampleSearch = await (await fetch("data/sample/search.json")).json(); } catch (e) { sampleSearch = []; }
      }
      return sampleSearch;
    }
    if (!searchCache[key]) {
      try { searchCache[key] = await (await fetch(`data/search/${key}.json`)).json(); } catch (e) { searchCache[key] = []; }
    }
    return searchCache[key];
  }

  let searchResults = [], searchSel = -1;
  async function runSearch(raw) {
    const q = raw.trim().toUpperCase();
    const ul = $("search-results");
    if (q.length < 2) { ul.hidden = true; $("search-input").setAttribute("aria-expanded", "false"); return; }

    const matches = [];
    // 1. Direct 10-digit BBL lookup
    if (/^[23]\d{9}$/.test(q)) {
      matches.push({ type: "bbl", bbl: q, title: `Building Lot ${q}`, meta: "Direct BBL lookup" });
    }
    // 2. Neighborhood / District matches
    if (districts) {
      districts.features.forEach((f) => {
        const p = f.properties;
        if (p.nm.toUpperCase().includes(q) || p.cd === q) {
          matches.push({ type: "cd", cd: p.cd, title: p.nm, meta: `${p.bo} District ${p.cd} · ${p.n.toLocaleString()} bldgs` });
        }
      });
    }
    // 3. Sharded street address matches
    const key = shardKeyForQuery(q);
    if (key) {
      const rows = await loadSearchShard(key);
      const terms = q.split(/\s+/).filter(Boolean);
      for (const r of rows) {
        const addr = r[1];
        if (terms.every((t) => addr.includes(t))) {
          matches.push({ type: "addr", bbl: r[0], addr, bo: r[2], cd: r[3], u: r[4], lng: r[5], lat: r[6], title: addr, meta: `${r[2]} · ${r[4]} units` });
          if (matches.length >= 12) break;
        }
      }
    }

    searchResults = matches.slice(0, 10);
    searchSel = searchResults.length ? 0 : -1;
    if (!searchResults.length) {
      ul.innerHTML = '<li class="muted" style="cursor:default">No matching address or neighborhood found</li>';
    } else {
      ul.innerHTML = searchResults.map((m, i) => `
        <li role="option" data-i="${i}" aria-selected="${i === 0 ? "true" : "false"}">
          <span class="sr-main">${esc(m.title)}</span>
          <span class="sr-meta">${esc(m.meta)}</span>
        </li>`).join("");
    }
    ul.hidden = false;
    $("search-input").setAttribute("aria-expanded", "true");
  }

  async function selectSearchItem(item) {
    $("search-results").hidden = true;
    $("search-input").setAttribute("aria-expanded", "false");
    $("search-input").value = item.title;
    switchTab("map");
    if (item.type === "cd") {
      flyToDistrict(item.cd, false);
    } else if (item.type === "addr") {
      if (map) map.flyTo({ center: [item.lng, item.lat], zoom: 16.2, pitch: 58, duration: 950 });
      openPanel({ b: item.bbl, bo: item.bo, cd: item.cd, u: item.u, ad: item.addr });
    } else if (item.type === "bbl") {
      const f = await getFacts(item.bbl);
      openPanel({ b: item.bbl, bo: f ? f.bo : (item.bbl[0] === "2" ? "BX" : "BK"), cd: f ? f.cd : "", u: f ? f.u : 0, ad: f ? f.addr : "" });
    }
  }

  // ------------------------------------------------------------------ Investigations Tab (Broadsheet + Interactive SVG Charts)
  function renderBarList(items, colorVar = "var(--signal)") {
    const maxV = Math.max(...items.map((x) => x.val), 1e-9);
    return `<div class="bar-list">${items.map((it) => `
      <div class="bar-item">
        <span class="bl" title="${esc(it.label)}">${esc(it.label)}</span>
        <div class="bt"><div class="bf" style="width:${Math.max(2, (it.val / maxV) * 100).toFixed(1)}%;background:${it.color || colorVar}"></div></div>
        <span class="bv">${esc(it.txt)}</span>
      </div>`).join("")}</div>`;
  }

  function renderInvestigations() {
    if (!digest) return;
    const s1Tiers = digest.study1_tiers || [];
    const s1Regs = digest.study1_regressions || [];
    const s2Conc = (digest.study2_concentration || []).filter((r) => r.top_pct === 1);
    const s2Markov = digest.study2_heat_markov || [];
    const s3Km = (digest.study3_km_survival || []).filter((r) => r.group_type === "classC_hazard_category" && r.group !== "other").sort((a, b) => b.km_median_days - a.km_median_days);
    const s3Mo = digest.study3_seasonality || [];
    const s4Cem = (digest.study4_cem || []).filter((r) => r.metric !== "units_residential");
    const s4Prev = (digest.study4_prevalence || []).find((r) => r.era === "post_moratorium_2022_2025") || {};
    const s5Rel = (digest.study5_aep_relapse || [])[0] || {};
    const s5Sales = (digest.study5_sales_het || []).filter((r) => ["clean_base_0C", "mild_base_1to4C", "distressed_base_5plusC"].includes(r.tier));

    const qReg = s1Regs.find((r) => r.slice === "quiet_0v_0c" && r.outcome === "label_class_c_any") || {};
    const pReg = s1Regs.find((r) => r.slice === "quiet_0v_0c_placebo" && r.outcome === "label_class_c_any") || {};

    $("hero-kpis").innerHTML = `
      <div class="hero-kpi">
        <div class="hk-num">${qReg.or ? qReg.or.toFixed(2) + "×" : "1.35×"}</div>
        <div class="hk-lbl">Portfolio Contagion Odds Ratio</div>
        <div class="hk-sub">Quiet buildings (0 complaints, 0 viols) per +1 SD sister-building Class C rate (p &lt; 10<sup>-34</sup>)</div>
      </div>
      <div class="hero-kpi kpi-amber">
        <div class="hk-num">50.4%</div>
        <div class="hk-lbl">OMO Dollars in Top 1% of Buildings</div>
        <div class="hk-sub">$196.1M in spine ($700M BX+BK all-time); 1.7% of buildings drive 48.2% of winter heat emergencies</div>
      </div>
      <div class="hero-kpi kpi-slate">
        <div class="hk-num">110d / 590d</div>
        <div class="hk-lbl">Median Time to Close "24-Hr" Class C</div>
        <div class="hk-sub">110d all Class C; 590d Mold, 265d Pests, 256d Lead Paint (Kaplan-Meier across 1.06M violations)</div>
      </div>
      <div class="hero-kpi kpi-teal">
        <div class="hk-num">${s4Prev.pct_1plus_open_C ? s4Prev.pct_1plus_open_C.toFixed(1) + "%" : "80.9%"}</div>
        <div class="hk-lbl">Evictions in Class C Hazardous Buildings</div>
        <div class="hk-sub">Post-moratorium (2022–25); 1.95× Class C/unit vs identical-size same-district peers</div>
      </div>`;

    const niceHaz = { mold: "Mold / Mildew", pests_vermin: "Pests / Rats", lead_paint: "Lead Paint (21d law)", walls_ceilings_floors: "Plaster / Walls", doors_windows_locks: "Doors / Locks", fire_safety: "Fire / Smoke / CO", water_plumbing: "Water / Plumbing", heat_hot_water: "Heat & Hot Water" };
    const niceCem = { vc_pu: "Class C / unit", open_c_pu: "Open Class C / unit", omo_pu: "Taxpayer OMO $ / unit", lit_n: "HPD Litigations", harass_lit: "Harassment Litigations" };
    const niceConc = { omo_usd: "Taxpayer OMO ($)", hw_probs_7w: "Winter Heat Complaints", evict_n: "Marshal Evictions", viol_c: "Class C Violations", open_c: "Open Class C", litig_n: "HPD Litigations" };
    const tierLabels = { "0_clean_0": "Sisters clean (0)", "1_low_lt0.05": "Sisters low (<0.05)", "2_med_0.05_0.15": "Sisters med (0.05–.15)", "3_high_0.15_0.35": "Sisters high (.15–.35)", "4_severe_0.35plus": "Sisters severe (0.35+)" };

    // Build SVG seasonality line chart for Study 3
    const moNames = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
    let seasonSvg = "";
    if (s3Mo.length === 12) {
      const W = 380, H = 152;
      const maxVol = Math.max(...s3Mo.map((m) => m.closed_problems));
      const bars = s3Mo.map((m, i) => {
        const bw = 20, x = 18 + i * 30, bh = (m.closed_problems / maxVol) * 90;
        return `<rect x="${x}" y="${128 - bh}" width="${bw}" height="${bh}" rx="2" fill="var(--rule)"/>
                <text x="${x + bw / 2}" y="144" text-anchor="middle" font-size="9" fill="var(--muted)" font-family="var(--font-mono)">${moNames[i]}</text>`;
      }).join("");
      const pts = s3Mo.map((m, i) => `${28 + i * 30},${128 - (m.pct_violation_issued / 80) * 90}`).join(" ");
      const dots = s3Mo.map((m, i) => `<circle cx="${28 + i * 30}" cy="${128 - (m.pct_violation_issued / 80) * 90}" r="3" fill="var(--signal)"/>`).join("");
      seasonSvg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
        <text x="18" y="13" font-size="9.5" fill="var(--signal)" font-weight="700">Red line: % yielding violation (68% Aug → 33% Dec)</text>
        <text x="18" y="26" font-size="9" fill="var(--muted)">Grey bars: Monthly closed complaints (peaks 365k in Jan)</text>
        ${bars}
        <polyline points="${pts}" fill="none" stroke="var(--signal)" stroke-width="2.2"/>
        ${dots}
      </svg>`;
    }

    $("studies-container").innerHTML = `
      <!-- STUDY 1 -->
      <article class="study-card">
        <div class="study-head">
          <div>
            <div class="study-num">Investigation 01 · Headline Finding</div>
            <h3>Silence Isn't Safe When a Landlord's Other Buildings Are Failing</h3>
            <p class="study-lead">While a building's own lack of complaints does not signal hidden danger on its own, linking 65,621 buildings into anonymized ownership portfolios changes the answer. Among <strong>38,110 completely quiet building-years</strong> (0 complaints &amp; 0 violations), sister-building Class C distress nearly triples next-year Class C risk (5.1% → 14.2%; controlled OR ${qReg.or || 1.35}, 95% CI [${qReg.ci_lo || 1.28}, ${qReg.ci_hi || 1.41}], shuffled-portfolio placebo OR ${pReg.or || 0.96}).</p>
          </div>
          <button type="button" class="map-jump-btn" data-jump-preset="contagion">Inspect on 3D Atlas →</button>
        </div>
        <div class="study-grid">
          <div class="chart-box">
            <h4>Quiet Buildings (0 Comp, 0 Viol): Next-12m Class C Rate</h4>
            ${renderBarList(s1Tiers.map((r) => ({ label: tierLabels[r.sister_tier] || r.sister_tier, val: r.pct_class_c_next12m, txt: r.pct_class_c_next12m.toFixed(1) + "%" })))}
          </div>
          <div class="chart-box">
            <h4>Controlled Contagion Robustness (OR per +1 SD, CD + Year FE)</h4>
            ${renderBarList(
              s1Regs.filter((r) => r.outcome === "label_class_c_any" && ["quiet_0v_0c", "quiet_never_sold", "quiet_headofficer_only", "phase4_silent", "all_multi_port", "quiet_0v_0c_placebo"].includes(r.slice))
                .map((r) => ({
                  label: { quiet_0v_0c: "Quiet (0 comp, 0 viol)", quiet_never_sold: "Quiet & never sold", quiet_headofficer_only: "Head Officer link only", phase4_silent: "Phase 4 'Silent'", all_multi_port: "All multi-bldg lots", quiet_0v_0c_placebo: "Shuffled placebo" }[r.slice],
                  val: r.or, txt: `${r.or.toFixed(2)}× [${r.ci_lo.toFixed(2)}, ${r.ci_hi.toFixed(2)}]`,
                  color: r.slice.includes("placebo") ? "var(--muted)" : "var(--signal)",
                }))
            )}
          </div>
        </div>
        <div class="study-caveat"><strong>Honest caveat:</strong> HPD registration contacts reflect the current snapshot; restricting strictly to buildings with zero DOF sales (2018–2025) yields an even stronger OR of 1.36. Top 0.5% of portfolios (191 portfolios) drive 50.0% of taxpayer OMO dollars (2.55× their share of units).</div>
      </article>

      <!-- STUDY 2 -->
      <article class="study-card">
        <div class="study-head">
          <div>
            <div class="study-num">Investigation 02 · Chronic Concentration</div>
            <h3>The 1% Driving NYC's Winter Heat &amp; Emergency Repair Crisis</h3>
            <p class="study-lead">NYC's housing distress is astonishingly concentrated in repeat offenders. Just <strong>1,766 buildings (1.7%)</strong> failed heat in all 7 consecutive winters (2018–2025), generating <strong>48.2% of all winter heat emergencies</strong>—yet <strong>79.6% have never entered AEP</strong>. Meanwhile, 1% of buildings absorb <strong>50.4% of taxpayer OMO emergency repair dollars</strong> (size-adjusted unit Gini = 0.917).</p>
          </div>
          <button type="button" class="map-jump-btn" data-jump-preset="heat7">Inspect 7-Winter Repeaters →</button>
        </div>
        <div class="study-grid">
          <div class="chart-box">
            <h4>Share of Bronx &amp; Brooklyn Totals in Top 1% of Buildings</h4>
            ${renderBarList(s2Conc.sort((a, b) => b.share_by_top_bldgs_pct - a.share_by_top_bldgs_pct).map((r) => ({ label: niceConc[r.metric] || r.metric, val: r.share_by_top_bldgs_pct, txt: `${r.share_by_top_bldgs_pct.toFixed(1)}% (u:${r.share_by_top_units_rate_pct.toFixed(0)}%)`, color: "var(--amber)" })))}
          </div>
          <div class="chart-box">
            <h4>Markov Persistence: % Failing Heat Again in Winter 2024–25</h4>
            ${renderBarList(s2Markov.map((r) => ({ label: `${r.prior_failed_winters_of_6} of 6 prior winters`, val: r.pct_fail_winter_2024_25, txt: `${r.pct_fail_winter_2024_25.toFixed(1)}%`, color: r.prior_failed_winters_of_6 >= 5 ? "var(--signal)" : "var(--slate)" })))}
          </div>
        </div>
        <div class="study-caveat"><strong>Size-adjusted note:</strong> "u:XX%" shows the share held by the top 1% of residential <em>units</em> ranked by per-unit rate, proving concentration is not merely a big-building artifact.</div>
      </article>

      <!-- STUDY 3 -->
      <article class="study-card">
        <div class="study-head">
          <div>
            <div class="study-num">Investigation 03 · Enforcement Breakdown</div>
            <h3>"24-Hour" Immediately Hazardous Violations Sit Open for Years — And Winter Bottlenecks Cut Enforcement in Half</h3>
            <p class="study-lead">Kaplan-Meier survival analysis across 1.06 million Class C violations (properly handling right-censoring) shows a median closure time of <strong>110 days</strong>—and <strong>590 days for Mold</strong>, <strong>265 days for Pests</strong>, and <strong>256 days for Lead Paint</strong> (legally a 21-day hazard). In winter, complaint volume doubles to 365k/month while violation-issuance rates collapse from <strong>67.7% in August to 33.2% in December</strong>.</p>
          </div>
          <button type="button" class="map-jump-btn" data-jump-layer="openc">Inspect Open Class C Map →</button>
        </div>
        <div class="study-grid">
          <div class="chart-box">
            <h4>Class C Survival: Kaplan-Meier Median Days to Close</h4>
            ${renderBarList(s3Km.map((r) => ({ label: niceHaz[r.group] || r.group, val: r.km_median_days, txt: `${r.km_median_days}d (${Math.round(r.km_still_open_1yr_pct)}% @1yr)`, color: r.km_median_days >= 250 ? "var(--signal)" : "var(--slate)" })))}
          </div>
          <div class="chart-box">
            <h4>Winter Congestion: Complaint Volume vs Violation Issuance</h4>
            ${seasonSvg}
          </div>
        </div>
        <div class="study-caveat"><strong>Nuance on False Certifications:</strong> Buildings caught with explicit <code>FALSE CERTIFICATION</code> actually had slightly fewer subsequent Class C violations than matched peers (0.84×), consistent with detection triggering active re-inspection pressure rather than impunity.</div>
      </article>

      <!-- STUDY 4 -->
      <article class="study-card">
        <div class="study-head">
          <div>
            <div class="study-num">Investigation 04 · Evictions &amp; Habitability</div>
            <h3>The Eviction–Hazard Paradox: 81% of Evictions Happen Inside Hazardous Buildings</h3>
            <p class="study-lead">Post-moratorium (2022–2025), <strong>80.9% of 31,202 executed marshal evictions</strong> occurred in buildings with 1+ open Class C hazard (<strong>60.9%</strong> with 5+, <strong>58.0%</strong> with open Rent-Impairing violations). Matched strictly on community district, fine unit-size bin, era, and building class (11,429 evicting vs 80,513 non-evicting buildings), evicting buildings carry <strong>1.95× more Class C hazards/unit</strong> and <strong>2.11× more harassment litigations</strong>. Event-study tracking shows complaints drop cleanly after eviction (<strong>-2.0 pp</strong>, flat pre-trend p = 0.60).</p>
          </div>
          <button type="button" class="map-jump-btn" data-jump-preset="evhaz">Inspect Evicting + Hazardous →</button>
        </div>
        <div class="study-grid">
          <div class="chart-box">
            <h4>Matched Ratio: Evicting ÷ Identical-Size Same-CD Non-Evicting</h4>
            ${renderBarList(s4Cem.map((r) => ({ label: niceCem[r.metric] || r.metric, val: r.ratio, txt: `${r.ratio.toFixed(2)}× [${r.ratio_ci_lo.toFixed(2)}, ${r.ratio_ci_hi.toFixed(2)}]`, color: "var(--crimson)" })))}
          </div>
          <div class="chart-box">
            <h4>Post-Moratorium Eviction Context (31,202 Executed Evictions)</h4>
            ${renderBarList([
              { label: "1+ Open Class C hazard", val: s4Prev.pct_1plus_open_C || 80.9, txt: (s4Prev.pct_1plus_open_C || 80.9).toFixed(1) + "%" },
              { label: "5+ Open Class C hazards", val: s4Prev.pct_5plus_open_C || 60.9, txt: (s4Prev.pct_5plus_open_C || 60.9).toFixed(1) + "%" },
              { label: "Open Rent-Impairing viol.", val: s4Prev.pct_1plus_open_rent_impairing || 58.0, txt: (s4Prev.pct_1plus_open_rent_impairing || 58.0).toFixed(1) + "%" },
              { label: "10+ Emergency complaints", val: s4Prev.pct_10plus_emerg_comp || 56.3, txt: (s4Prev.pct_10plus_emerg_comp || 56.3).toFixed(1) + "%" },
              { label: "Recent HPD litigation", val: s4Prev.pct_recent_litig || 46.1, txt: (s4Prev.pct_recent_litig || 46.1).toFixed(1) + "%" },
            ], "var(--crimson)")}
          </div>
        </div>
        <div class="study-caveat"><strong>Interpretation:</strong> Eviction records are at the building level and cannot establish individual tenant motives, but the event-study confirms hazards ramp up <em>prior</em> to eviction and complaints fall afterward—consistent with chronic habitability disputes or displacement of complaining tenants.</div>
      </article>

      <!-- STUDY 5 -->
      <article class="study-card">
        <div class="study-head">
          <div>
            <div class="study-num">Investigation 05 · Interventions, Sales &amp; Vacates</div>
            <h3>AEP Cuts Emergency Repairs While Active — Yet 70% Relapse After Discharge; Sales Don't Cure Distressed Buildings</h3>
            <p class="study-lead">Quasi-experimental DiD shows HPD's Alternative Enforcement Program cuts quarterly OMO probability by ~20 pp during intervention, but among <strong>${num(s5Rel.discharged_bldgs || 1022)} discharged buildings</strong>, <strong>${(s5Rel.pct_5plus_classC_within_2y || 70.2).toFixed(1)}%</strong> accumulate 5+ new Class C hazards within 2 years and <strong>${(s5Rel.pct_reentered_aep || 26.9).toFixed(1)}% re-enter AEP</strong>. Meanwhile, splitting 8,500 whole-building sales by pre-sale condition shows distressed buildings (n=674) do not improve after sale (+1.8 pp Class C), while evictions dip slightly across all sale tiers. Finally, 58.4% of vacate orders are Fire Damage—explaining why Phase 4's pooled silent RR looked lower (0.65) than DOB physical hazards alone (0.86, CI [0.72, 1.05]).</p>
          </div>
          <button type="button" class="map-jump-btn" data-jump-layer="omo">Inspect OMO Spend Map →</button>
        </div>
        <div class="study-grid">
          <div class="chart-box">
            <h4>Post-Discharge AEP Relapse Within 2 Years (n = ${num(s5Rel.discharged_bldgs || 1022)})</h4>
            ${renderBarList([
              { label: "5+ New Class C hazards", val: s5Rel.pct_5plus_classC_within_2y || 70.2, txt: (s5Rel.pct_5plus_classC_within_2y || 70.2).toFixed(1) + "%", color: "var(--signal)" },
              { label: "New taxpayer OMO needed", val: s5Rel.pct_new_omo_within_2y || 62.0, txt: (s5Rel.pct_new_omo_within_2y || 62.0).toFixed(1) + "%", color: "var(--amber)" },
              { label: "15+ New Class C hazards", val: s5Rel.pct_15plus_classC_within_2y || 51.7, txt: (s5Rel.pct_15plus_classC_within_2y || 51.7).toFixed(1) + "%", color: "var(--signal)" },
              { label: "Re-entered AEP program", val: s5Rel.pct_reentered_aep || 26.9, txt: (s5Rel.pct_reentered_aep || 26.9).toFixed(1) + "%", color: "var(--teal)" },
            ])}
          </div>
          <div class="chart-box">
            <h4>Post-Sale DiD Change by Pre-Sale Condition (Class C pp)</h4>
            ${renderBarList(
              s5Sales.filter((r) => r.outcome === "any_classC").map((r) => ({
                label: { clean_base_0C: "Clean (0 Class C)", mild_base_1to4C: "Mild (1–4 Class C)", distressed_base_5plusC: "Distressed (5+ C)" }[r.tier],
                val: Math.max(0.1, Math.abs(r.avg_post * 100)),
                txt: `${r.avg_post >= 0 ? "+" : ""}${(r.avg_post * 100).toFixed(2)} pp`,
                color: "var(--slate)",
              }))
            )}
          </div>
        </div>
      </article>`;

    // Wire "Inspect on 3D Atlas" jump buttons
    $("studies-container").querySelectorAll(".map-jump-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchTab("map");
        if (btn.dataset.jumpPreset) {
          applyPreset(btn.dataset.jumpPreset);
        } else if (btn.dataset.jumpLayer) {
          activePreset = null;
          layerKey = btn.dataset.jumpLayer;
          $("layer").value = layerKey;
          applyStyle();
        }
      });
    });
  }

  // ------------------------------------------------------------------ District Rankings Table
  function renderRankings() {
    if (!districts) return;
    let rows = districts.features.map((f) => ({
      cd: f.properties.cd, bo: f.properties.bo, nm: f.properties.nm, n: f.properties.n,
      ...f.properties.s,
    }));
    if (rankBoro) rows = rows.filter((r) => r.bo === rankBoro);

    const { col, dir } = rankSort;
    rows.sort((a, b) => {
      if (col === "nm") return dir * a.nm.localeCompare(b.nm);
      return dir * ((a[col] || 0) - (b[col] || 0));
    });

    const maxOmo = Math.max(...rows.map((r) => r.omo_m), 1);
    const maxHeat = Math.max(...rows.map((r) => r.heat7_n), 1);

    $("rankings-tbody").innerHTML = rows.map((r) => `
      <tr data-cd="${r.cd}">
        <th scope="row">
          <span class="roundel ${r.bo === "BX" ? "roundel-bx" : "roundel-bk"}" style="width:19px;height:19px;font-size:8.5px;margin-right:6px;vertical-align:middle">${r.bo}</span>
          ${esc(r.nm)} <span class="muted">(${r.cd})</span>
        </th>
        <td class="num" data-label="Buildings">${r.n.toLocaleString()}</td>
        <td class="num ${r.omo_m >= maxOmo * 0.65 ? "cell-hot" : ""}" data-label="OMO Spend">$${r.omo_m.toFixed(1)}M</td>
        <td class="num" data-label="OMO $/Unit">$${Math.round(r.omo_pu).toLocaleString()}</td>
        <td class="num ${r.heat7_n >= maxHeat * 0.6 ? "cell-hot" : ""}" data-label="6-7 Winter Heat">${r.heat7_n.toLocaleString()}</td>
        <td class="num" data-label="Open Class C/Unit">${r.open_c_pu.toFixed(2)}</td>
        <td class="num" data-label="Evictions / 1k">${r.ev_p1k.toFixed(1)}</td>
        <td class="num" data-label="Evict + 5+ Open C">${r.eh_n.toLocaleString()}</td>
        <td class="num" data-label="Quiet + Distressed Port.">${r.qp_n.toLocaleString()}</td>
      </tr>`).join("");

    $("rankings-tbody").querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        switchTab("map");
        flyToDistrict(tr.dataset.cd, false);
      });
    });

    document.querySelectorAll("#rankings-table thead th").forEach((th) => {
      if (th.dataset.sort === col) th.setAttribute("aria-sort", dir === -1 ? "descending" : "ascending");
      else th.removeAttribute("aria-sort");
    });
    const colLabel = document.querySelector(`#rankings-table thead th[data-sort="${col}"]`)?.textContent || col;
    $("rankings-meta").textContent = `Showing ${rows.length} neighborhoods · sorted by ${colLabel}`;
  }

  // ------------------------------------------------------------------ Tabs & Playback
  function switchTab(view) {
    document.querySelectorAll('.nav-tabs [role="tab"]').forEach((t) => {
      const sel = t.dataset.view === view;
      t.setAttribute("aria-selected", String(sel));
      t.tabIndex = sel ? 0 : -1;
    });
    ["map", "studies", "districts"].forEach((v) => {
      $("view-" + v).hidden = v !== view;
    });
    if (view === "map" && map) setTimeout(() => map.resize(), 40);
    writeHash();
  }

  function applyPreset(pKey) {
    if (activePreset === pKey) {
      activePreset = null;
    } else {
      activePreset = pKey;
      layerKey = PRESETS[pKey].layer;
      $("layer").value = layerKey;
      // If zoomed way out, zoom gently into Bronx/Brooklyn hot corridor so buildings are visible
      if (map && map.getZoom() < 12.6 && mode === "tiles") {
        map.easeTo({ center: [-73.908, 40.838], zoom: 13.6, pitch: 54, duration: 900 });
      }
    }
    applyStyle();
  }

  function stopPlayback() {
    if (playTimer) { clearInterval(playTimer); playTimer = null; }
    $("play").innerHTML = "&#9654;";
    $("play").setAttribute("aria-label", "Play quarterly snapshots");
  }

  // ------------------------------------------------------------------ Init
  async function head(url) {
    try { return (await fetch(url, { method: "HEAD" })).ok; } catch (e) { return false; }
  }
  function calcSampleCenter(g) {
    let xs = 0, ys = 0, n = 0;
    for (const f of g.features.slice(0, 400)) {
      const c = (f.geometry.type === "Polygon" ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0])[0];
      xs += c[0]; ys += c[1]; n++;
    }
    return [xs / n, ys / n];
  }

  async function init() {
    try { meta = await (await fetch("data/meta.json")).json(); } catch (e) { meta = null; }
    try { digest = await (await fetch("data/studies_digest.json")).json(); } catch (e) { digest = null; }
    const hasTiles = !new URLSearchParams(location.search).has("sample") && await head("data/buildings.pmtiles");
    mode = hasTiles ? "tiles" : "sample";

    if (mode === "sample") {
      sampleGeo = await (await fetch("data/sample/buildings.geojson")).json();
      snaps = sampleGeo.snapshots;
      sampleCenter = calcSampleCenter(sampleGeo);
    } else {
      snaps = meta.snapshots;
    }

    try { districts = await (await fetch("data/districts.json")).json(); } catch (e) { districts = null; }
    if (districts) {
      districts.features.forEach((f) => { districtById[f.properties.cd] = f.properties; });
      buildDistrictScales();
    }

    idx = snaps.length - 1;
    $("slider").max = snaps.length - 1;

    // Populate grouped layer select
    const groups = {};
    Object.entries(LAYERS).forEach(([k, L]) => {
      if (!groups[L.group]) {
        const og = document.createElement("optgroup");
        og.label = L.group;
        $("layer").appendChild(og);
        groups[L.group] = og;
      }
      const o = document.createElement("option");
      o.value = k;
      o.textContent = L.label;
      groups[L.group].appendChild(o);
    });

    if (districts) {
      districts.features.map((f) => f.properties).sort((a, b) => (a.bo + a.cd).localeCompare(b.bo + b.cd)).forEach((p) => {
        const o = document.createElement("option");
        o.value = p.cd;
        o.textContent = `${p.bo} ${p.cd} · ${p.nm}`;
        $("district").appendChild(o);
      });
    }

    const start = readHash();
    if (start.layer) layerKey = start.layer;
    if (start.idx != null && start.idx < snaps.length) idx = start.idx;
    if (start.preset) activePreset = start.preset;
    $("layer").value = layerKey;

    const sampleCd = mode === "sample" ? (sampleGeo.features[0] && sampleGeo.features[0].properties.cd) : null;
    if (mode === "sample") {
      const p = districtById[sampleCd];
      $("sample-note").hidden = false;
      $("sample-note").innerHTML = `<strong>Sample Atlas Mode.</strong> Individual 3D buildings loaded for ${esc(p ? p.nm : sampleCd)} (${sampleGeo.features.length.toLocaleString()} footprints). Zoom out for all 30 districts, or run <code>make map</code> locally for all 120,705 footprints.`;
    }

    renderInvestigations();
    renderRankings();
    if (start.tab) switchTab(start.tab);

    if (mode === "tiles") {
      const protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      protocol.add(new pmtiles.PMTiles(new URL("data/buildings.pmtiles", location.href).href));
    }

    const dark = renderedTheme() === "dark";
    const sv = start.view;
    map = new maplibregl.Map({
      container: "map",
      center: sv ? [sv[0], sv[1]] : (mode === "sample" ? sampleCenter : [-73.920, 40.735]),
      zoom: sv ? sv[2] : (mode === "sample" ? 14.3 : 10.6),
      pitch: sv ? sv[3] : 52,
      bearing: sv ? sv[4] : -18,
      maxPitch: 75,
      minZoom: 9.2,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          esriLight: {
            type: "raster",
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256, maxzoom: 15,
          },
          esriLightRef: {
            type: "raster",
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256, maxzoom: 15,
          },
          esriDark: {
            type: "raster",
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256, maxzoom: 15,
          },
          esriDarkRef: {
            type: "raster",
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"],
            tileSize: 256, maxzoom: 15,
          },
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": dark ? "#0d1117" : "#ede8dc" } },
          { id: "basemap-light", type: "raster", source: "esriLight", layout: { visibility: !dark ? "visible" : "none" }, paint: { "raster-opacity": 0.85 } },
          { id: "basemap-light-ref", type: "raster", source: "esriLightRef", layout: { visibility: !dark ? "visible" : "none" }, paint: { "raster-opacity": 0.75 } },
          { id: "basemap-dark", type: "raster", source: "esriDark", layout: { visibility: dark ? "visible" : "none" }, paint: { "raster-opacity": 0.88 } },
          { id: "basemap-dark-ref", type: "raster", source: "esriDarkRef", layout: { visibility: dark ? "visible" : "none" }, paint: { "raster-opacity": 0.72 } },
        ],
      },
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "NYC Open Data · Esri Gray Canvas · MapLibre" }), "bottom-left");
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-left");

    map.on("load", () => {
      if (mode === "tiles") {
        map.addSource("bld", { type: "vector", url: "pmtiles://" + new URL("data/buildings.pmtiles", location.href).href, minzoom: 11, maxzoom: 16 });
        map.addLayer({
          id: "context", type: "fill-extrusion", source: "bld", "source-layer": "context", minzoom: 14,
          paint: { "fill-extrusion-color": dark ? "#232a36" : "#cfc9bc", "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.45 },
        });
        map.addLayer({
          id: "scored", type: "fill-extrusion", source: "bld", "source-layer": "scored", minzoom: 12,
          paint: {
            "fill-extrusion-color": buildingColorExpr(LAYERS[layerKey], idx),
            "fill-extrusion-height": ["get", "h"],
            "fill-extrusion-base": 0,
            "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 12.1, 0, 13.2, 0.94],
          },
        });
      } else {
        map.addSource("bld", { type: "geojson", data: sampleGeo });
        map.addLayer({
          id: "scored", type: "fill-extrusion", source: "bld",
          paint: { "fill-extrusion-color": buildingColorExpr(LAYERS[layerKey], idx), "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.94 },
        });
      }

      if (districts) {
        map.addSource("districts", { type: "geojson", data: districts });
        map.addLayer({
          id: "districts-fill", type: "fill", source: "districts",
          paint: { "fill-color": districtColorExpr(LAYERS[layerKey], idx), "fill-opacity": ["interpolate", ["linear"], ["zoom"], 11.4, 0.68, 12.9, 0] },
        }, "scored");
        map.addLayer({
          id: "districts-line", type: "line", source: "districts",
          paint: { "line-color": dark ? "#8e9bb0" : "#515a69", "line-width": 1.2, "line-opacity": ["interpolate", ["linear"], ["zoom"], 11.4, 0.85, 13.2, 0.2] },
        }, "scored");
        map.on("mousemove", "districts-fill", (e) => { if (map.getZoom() < 12.6) hoverDistrict(e); });
        map.on("mouseleave", "districts-fill", () => { $("hover").hidden = true; map.getCanvas().style.cursor = ""; });
        map.on("click", "districts-fill", (e) => { if (map.getZoom() < 12.6) flyToDistrict(e.features[0].properties.cd, false); });
      }

      const selSrc = mode === "tiles" ? { source: "bld", "source-layer": "scored" } : { source: "bld" };
      map.addLayer({
        id: "selected", type: "fill-extrusion", ...selSrc, filter: ["==", ["get", "b"], selectedBbl],
        paint: { "fill-extrusion-color": "#00d4ff", "fill-extrusion-height": ["+", ["get", "h"], 2.2], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.96 },
      });

      const onZoom = () => {
        const dvw = !!districts && map.getZoom() < DISTRICT_ZOOM;
        if (dvw !== districtView) { districtView = dvw; renderLegend(); }
        $("zoom-hint").textContent = dvw ? "District view — click any district or zoom in for 3D buildings" : "3D Building view — click any building for its Report Card";
      };
      map.on("zoom", onZoom);
      map.on("moveend", writeHash);
      districtView = !!districts && map.getZoom() < DISTRICT_ZOOM;
      onZoom();

      map.on("mousemove", "scored", hoverBuilding);
      map.on("mouseleave", "scored", () => { $("hover").hidden = true; map.getCanvas().style.cursor = ""; });
      map.on("click", "scored", (e) => { if (e.features && e.features.length) openPanel(e.features[0].properties); });
      applyStyle();
    });
  }

  // ------------------------------------------------------------------ Wiring
  function wire() {
    $("layer").addEventListener("change", (e) => { layerKey = e.target.value; applyStyle(); });
    $("slider").addEventListener("input", (e) => { stopPlayback(); idx = +e.target.value; applyStyle(); });
    $("borough").addEventListener("change", () => {
      const d = $("district").value;
      if (d && districtById[d] && $("borough").value && districtById[d].bo !== $("borough").value) $("district").value = "";
      applyStyle();
    });
    $("district").addEventListener("change", (e) => {
      if (e.target.value) flyToDistrict(e.target.value, true);
      else applyStyle();
    });
    document.querySelectorAll(".preset-chip").forEach((btn) => {
      btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
    });
    $("clear-filters").addEventListener("click", () => {
      activePreset = null;
      $("borough").value = "";
      $("district").value = "";
      applyStyle();
    });
    $("help-btn").addEventListener("click", () => {
      const h = $("layer-help");
      h.hidden = !h.hidden;
      $("help-btn").setAttribute("aria-expanded", String(!h.hidden));
    });
    $("basemap-btn").addEventListener("click", () => {
      basemapOn = !basemapOn;
      $("basemap-btn").textContent = basemapOn ? "Street map: On" : "Street map: Off";
      $("basemap-btn").setAttribute("aria-pressed", String(basemapOn));
      syncThemeToMap();
    });
    $("reset-view").addEventListener("click", () => {
      if (!map) return;
      map.easeTo({
        center: mode === "sample" ? sampleCenter : [-73.920, 40.735],
        zoom: mode === "sample" ? 14.3 : 10.6,
        pitch: 52, bearing: -18, duration: 850,
      });
    });
    $("play").addEventListener("click", () => {
      if (playTimer) { stopPlayback(); return; }
      $("play").innerHTML = "&#10074;&#10074;";
      $("play").setAttribute("aria-label", "Pause quarterly playback");
      playTimer = setInterval(() => { idx = (idx + 1) % snaps.length; applyStyle(); }, 900);
    });
    $("panel-close").addEventListener("click", () => { $("panel").hidden = true; currentProps = null; setSelected(""); });
    $("theme-btn").addEventListener("click", toggleTheme);

    // Native <dialog closedby="any"> + Safari light-dismiss fallback (modern-web-guidance: dialog & light-dismiss-a-dialog)
    const dlg = $("about-dialog");
    $("about-btn").addEventListener("click", () => dlg.showModal());
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      const outside = (e) => {
        const r = dlg.getBoundingClientRect();
        return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
      };
      let pressedOutside = false;
      dlg.addEventListener("pointerdown", (e) => { pressedOutside = outside(e); });
      dlg.addEventListener("pointerup", (e) => { if (pressedOutside && outside(e)) dlg.close(); });
    }

    // Accessible Tabs with arrow key support
    const tabs = Array.from(document.querySelectorAll('.nav-tabs [role="tab"]'));
    tabs.forEach((tab, ti) => {
      tab.addEventListener("click", () => switchTab(tab.dataset.view));
      tab.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const next = tabs[(ti + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
          next.focus();
          switchTab(next.dataset.view);
        }
      });
    });

    // District Rankings sorting & borough filter
    document.querySelectorAll("#rankings-table thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const c = th.dataset.sort;
        if (rankSort.col === c) rankSort.dir *= -1;
        else rankSort = { col: c, dir: c === "nm" ? 1 : -1 };
        renderRankings();
      });
    });
    document.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        rankBoro = btn.dataset.rboro;
        document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
        renderRankings();
      });
    });

    // Search input & keyboard navigation
    let searchTimer = null;
    $("search-input").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => runSearch(e.target.value), 120);
    });
    $("search-input").addEventListener("keydown", (e) => {
      const ul = $("search-results");
      if (ul.hidden || !searchResults.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        searchSel = (searchSel + (e.key === "ArrowDown" ? 1 : -1) + searchResults.length) % searchResults.length;
        ul.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", String(i === searchSel)));
      } else if (e.key === "Enter" && searchSel >= 0) {
        e.preventDefault();
        selectSearchItem(searchResults[searchSel]);
      } else if (e.key === "Escape") {
        ul.hidden = true;
        $("search-input").setAttribute("aria-expanded", "false");
      }
    });
    $("search-results").addEventListener("click", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) selectSearchItem(searchResults[+li.dataset.i]);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".search-wrap")) {
        $("search-results").hidden = true;
        $("search-input").setAttribute("aria-expanded", "false");
      }
    });

    // Global keyboard shortcuts: `/` focuses search, Esc closes Report Card, ←/→ steps quarterly snapshots
    document.addEventListener("keydown", (e) => {
      const inField = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
      if (e.key === "/" && !inField) {
        e.preventDefault();
        $("search-input").focus();
      } else if (e.key === "Escape" && !$("panel").hidden && !dlg.open) {
        $("panel").hidden = true; currentProps = null; setSelected("");
      } else if (!inField && LAYERS[layerKey].kind === "series" && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
        stopPlayback();
        idx = Math.max(0, Math.min(snaps.length - 1, idx + (e.key === "ArrowRight" ? 1 : -1)));
        applyStyle();
      }
    });
  }

  wire();
  init().catch((e) => {
    console.error(e);
    $("legend").textContent = "Could not load atlas data: " + e.message;
  });
  window.__cgm = { get map() { return map; }, set: (k, i) => { if (k && LAYERS[k]) layerKey = k; if (i != null) idx = i; $("layer").value = layerKey; applyStyle(); }, open: openPanel, switchTab };
})();
