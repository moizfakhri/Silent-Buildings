"""Phase 6 (Upgraded): build the data behind the NYC Housing Monitor 3D map & investigations site (app/web/data).

    python pipelines/build_map.py

Outputs under app/web/data/
  buildings.pmtiles    vector tiles, layers `scored` (120k footprints, 16-snapshot score strings +
                       study layers: heat recidivism, zombie Class C, OMO spend, portfolio contagion, evictions)
                       and `context` (313k other footprints)
  facts/<prefix>.json  per-block Building Report Card data (gitignored)
  search/<key>.json    sharded street-address & BBL search index with centroids (gitignored)
  districts.json       30 community-district shapes with neighborhood names, 16-snapshot averages & study totals (committed)
  studies_digest.json  aggregate findings & interactive chart datasets from Studies 1-5 (committed)
  sample/              one community district as GeoJSON + facts + search index (committed)

No owner, tenant, corporate or contact names are ever stored or emitted.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "building_footprints"
RAW_ALL = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
STUDIES_PROC = PROC / "studies"
STUDIES_REP = ROOT / "reports" / "studies"
OUT = ROOT / "app" / "web" / "data"
DEMOLISHED = {"Demolition", "Marked for Demolition", "Investigate Demolition"}

FACT_COLS = {  # name in facts -> (features column, decimals)
    "complaints12": ("loud_prob_n_12m", 0), "c311_12": ("loud_311_n_12m", 0), "open_viol": ("viol_open_n", 0), "viol12": ("viol_n_12m", 0),
    "viol_c12": ("viol_c_n_12m", 0), "evict12": ("evict_n_12m", 0), "dob12": ("dob_n_12m", 0), "omo_prior": ("prior_omo_n", 0),
    "litig_prior": ("prior_litig_n", 0), "vacate_prior": ("prior_vacate_n", 0), "aep_prior": ("prior_aep_n", 0),
}

# Official NYC Community District neighborhood names (Bronx 201-212, Brooklyn 301-318)
CD_NAMES = {
    "201": "Mott Haven & Melrose",
    "202": "Hunts Point & Longwood",
    "203": "Morrisania & Crotona",
    "204": "Highbridge & Concourse",
    "205": "Fordham & University Heights",
    "206": "Belmont, East Tremont & West Farms",
    "207": "Kingsbridge Heights & Bedford Park",
    "208": "Riverdale, Fieldston & Kingsbridge",
    "209": "Soundview, Parkchester & Castle Hill",
    "210": "Throgs Neck, Co-op City & Pelham Bay",
    "211": "Pelham Parkway, Morris Park & Laconia",
    "212": "Wakefield, Williamsbridge & Woodlawn",
    "301": "Williamsburg & Greenpoint",
    "302": "Downtown Brooklyn, Fort Greene & Boerum Hill",
    "303": "Bedford-Stuyvesant",
    "304": "Bushwick",
    "305": "East New York & Starrett City",
    "306": "Park Slope, Carroll Gardens & Red Hook",
    "307": "Sunset Park & Windsor Terrace",
    "308": "Crown Heights North & Prospect Heights",
    "309": "Crown Heights South & Prospect Lefferts",
    "310": "Bay Ridge & Dyker Heights",
    "311": "Bensonhurst & Bath Beach",
    "312": "Borough Park & Kensington",
    "313": "Coney Island & Brighton Beach",
    "314": "Flatbush & Midwood",
    "315": "Sheepshead Bay & Gerritsen Beach",
    "316": "Brownsville & Ocean Hill",
    "317": "East Flatbush",
    "318": "Canarsie & Flatlands",
}


def parse_geom(text):
    try:
        return json.loads(text)
    except ValueError:
        return ast.literal_eval(text)


def round_coords(c, nd=6):
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [round_coords(x, nd) for x in c]


def geom_centroid(g) -> tuple[float, float]:
    ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    return round(sum(xs) / len(xs), 5), round(sum(ys) / len(ys), 5)


def three(a):
    return "".join(f"{int(v):03d}" for v in a)


def load_scores():
    """One frame of per-(bbl, snapshot) values for the 16 out-of-time snapshots."""
    con = duckdb.connect()
    p3 = f"read_parquet('{PROC / 'scores_phase3.parquet'}')"
    af = f"read_parquet('{PROC / 'phase4' / 'analysis_frame.parquet'}')"
    cols = ["bbl", "snapshot_date", "static_unitsres", "p_hat", "gap_rank", "silent", "access_blocked", "loud_nacc_share_12m", "loud_closed_n_12m",
            "community_district", "static_borough"] + sorted({c for c, _ in FACT_COLS.values()})
    df = con.sql(f"""SELECT a.{', a.'.join(cols)}, s.score AS risk
                     FROM {af} a JOIN {p3} s ON s.bbl = a.bbl AND CAST(s.snapshot_date AS DATE) = CAST(a.snapshot_date AS DATE)""").df()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    return df


def load_building_enrichment(bbls: np.ndarray) -> pd.DataFrame:
    """Load PLUTO addresses, Study 1 portfolio summaries, Study 2 distress profiles, and hazard category breakdowns."""
    con = duckdb.connect()
    con.execute("SET threads=6")

    # 1. PLUTO addresses & zipcodes (no ownername ever selected!)
    pluto = con.sql(f"""
        SELECT lpad(CAST(try_cast(bbl AS DOUBLE)::BIGINT AS VARCHAR), 10, '0') AS bbl,
               trim(coalesce(address, '')) AS addr,
               trim(coalesce(zipcode, '')) AS zip
        FROM read_parquet('{RAW_ALL / "pluto/*.parquet"}')
    """).df().drop_duplicates("bbl").set_index("bbl")

    # 2. Study 2 distress profile & Study 1 anonymized portfolio summary
    prof = pd.read_parquet(STUDIES_PROC / "building_distress_profile.parquet").set_index("bbl")
    port = pd.read_parquet(STUDIES_PROC / "portfolio_building_summary.parquet").set_index("bbl")

    # 3. Open Class C median age (days as of 2026-11-11) & hazard category breakdown (2018+ Class C)
    haz = con.sql(f"""
        WITH v AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    lpad(boroid, 1, '0') || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                violationstatus,
                try_cast(left(inspectiondate, 10) AS DATE) AS insp_dt,
                lower(coalesce(novdescription, '')) AS descr
            FROM read_parquet('{RAW_ALL / "hpd_violations/*.parquet"}')
            WHERE class = 'C'
              AND try_cast(left(inspectiondate, 10) AS DATE) BETWEEN DATE '2018-01-01' AND DATE '2026-11-11'
        )
        SELECT bbl,
               round(median(datediff('day', insp_dt, DATE '2026-11-11')) FILTER (WHERE violationstatus = 'Open'), 0) AS open_c_med_d,
               count(*) FILTER (WHERE descr LIKE '%heat%' OR descr LIKE '%hot water%') AS h_heat,
               count(*) FILTER (WHERE descr LIKE '%lead-based%' OR descr LIKE '%lead paint%') AS h_lead,
               count(*) FILTER (WHERE descr LIKE '%mold%' OR descr LIKE '%mildew%') AS h_mold,
               count(*) FILTER (WHERE descr LIKE '%mice%' OR descr LIKE '%roach%' OR descr LIKE '%rat%' OR descr LIKE '%vermin%' OR descr LIKE '%pest%' OR descr LIKE '%bedbug%') AS h_pests,
               count(*) FILTER (WHERE descr LIKE '%leak%' OR descr LIKE '%plumb%' OR descr LIKE '%water%' OR descr LIKE '%pipe%' OR descr LIKE '%toilet%' OR descr LIKE '%sink%') AS h_water,
               count(*) FILTER (WHERE descr LIKE '%smoke%' OR descr LIKE '%carbon monoxide%' OR descr LIKE '%fire%' OR descr LIKE '%sprinkler%' OR descr LIKE '%self-closing%') AS h_fire,
               count(*) FILTER (WHERE descr LIKE '%lock%' OR descr LIKE '%door%' OR descr LIKE '%window%' OR descr LIKE '%intercom%') AS h_doors,
               count(*) FILTER (WHERE descr LIKE '%plaster%' OR descr LIKE '%paint%' OR descr LIKE '%ceiling%' OR descr LIKE '%wall%' OR descr LIKE '%floor%') AS h_walls
        FROM v GROUP BY 1
    """).df().set_index("bbl")

    out = pd.DataFrame(index=pd.Index(bbls, name="bbl"))
    out = out.join(pluto, how="left")
    out = out.join(prof[["borough", "units_residential", "open_c", "viol_c", "omo_n", "omo_usd", "evict_n", "litig_n", "aep_n", "bad_winters_3plus", "hw_probs_7w"]], how="left")
    out = out.join(port[["port_bldgs", "port_units", "reg_group", "sister_vc_pu_22_25"]], how="left")
    out = out.join(haz, how="left")

    # Peer percentile of open Class C per unit within (borough x size_bracket)
    out["u_br"] = pd.cut(out["units_residential"].fillna(3), bins=[0, 5, 19, 49, 100000], labels=False)
    out["_oc_pu"] = out["open_c"].fillna(0) / out["units_residential"].fillna(3).clip(lower=1)
    out["peer_pct"] = (out.groupby(["borough", "u_br"])["_oc_pu"].rank(pct=True) * 100).round(0).fillna(0).astype(int)
    con.close()
    return out


def percentile_codes(mat):
    """0..998 percentile of each value within its snapshot column (NaN -> 999)."""
    out = np.full(mat.shape, 999, dtype=int)
    for j in range(mat.shape[1]):
        col = mat[:, j]
        ok = ~np.isnan(col)
        r = pd.Series(col[ok]).rank(method="average", pct=True).to_numpy()
        out[ok, j] = np.minimum((r * 998).astype(int), 998)
    return out


def build_studies_digest():
    """Compile a compact committed JSON digest of Studies 1-5 for the Investigations & Rankings tabs."""
    def load_csv(name):
        p = STUDIES_REP / name
        return pd.read_csv(p).replace({np.nan: None}).to_dict(orient="records") if p.exists() else []

    digest = {
        "generated": time.strftime("%Y-%m-%d"),
        "study1_tiers": load_csv("study1_quiet_building_tiers.csv"),
        "study1_regressions": load_csv("study1_contagion_regressions.csv"),
        "study1_portfolio_size": load_csv("study1_portfolio_size_gradient.csv"),
        "study1_reg_groups": load_csv("study1_registration_groups.csv"),
        "study1_port_conc": load_csv("study1_portfolio_concentration.csv"),
        "study1_walkforward": load_csv("study1_walkforward_lift.csv"),
        "study2_concentration": load_csv("study2_concentration.csv"),
        "study2_heat_recidivism": load_csv("study2_heat_recidivism.csv"),
        "study2_heat_markov": load_csv("study2_heat_markov_persistence.csv"),
        "study2_omo_worktype": load_csv("study2_omo_by_worktype.csv"),
        "study2_omo_recidivism": load_csv("study2_omo_recidivism.csv"),
        "study3_funnel": load_csv("study3_complaint_funnel.csv"),
        "study3_km_survival": load_csv("study3_km_survival.csv"),
        "study3_seasonality": load_csv("study3_complaint_seasonality.csv"),
        "study3_false_cert": load_csv("study3_false_certification_matched.csv"),
        "study4_prevalence": load_csv("study4_eviction_prevalence.csv"),
        "study4_cem": load_csv("study4_cem_comparison.csv"),
        "study4_glm": load_csv("study4_glm_regressions.csv"),
        "study4_event_study": load_csv("study4_event_study.csv"),
        "study5_vacate_rr": load_csv("study5_vacate_subtype_silent_rr.csv"),
        "study5_vacate_traj": load_csv("study5_vacate_trajectories.csv"),
        "study5_sales_het": load_csv("study5_sales_heterogeneous.csv"),
        "study5_aep_ev": load_csv("study5_aep_event_study.csv"),
        "study5_aep_relapse": load_csv("study5_aep_relapse.csv"),
    }
    (OUT / "studies_digest.json").write_text(json.dumps(digest, separators=(",", ":")))
    print(f"studies_digest.json: {(OUT / 'studies_digest.json').stat().st_size / 1e3:.1f} KB", flush=True)


def search_shard_key(addr: str) -> str:
    """Two-character shard key from the first alphabetic token (street name), fallback to first 2 chars."""
    tokens = re.findall(r"[A-Z0-9]+", addr.upper())
    # Skip leading house number to shard evenly by street name
    street = next((t for t in tokens if any(c.isalpha() for c in t)), tokens[0] if tokens else "00")
    key = re.sub(r"[^A-Z0-9]", "", street)[:2].ljust(2, "_")
    return key


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facts").mkdir(exist_ok=True)
    (OUT / "search").mkdir(exist_ok=True)
    work = ROOT / "data" / "interim" / "map"
    work.mkdir(parents=True, exist_ok=True)

    df = load_scores()
    snaps = sorted(df.snapshot_date.unique())
    assert len(snaps) == 16
    spine = pd.read_parquet(PROC / "spine.parquet").set_index("bbl")
    bbls = np.array(sorted(df.bbl.unique()))
    bi = {b: i for i, b in enumerate(bbls)}
    nb = len(bbls)
    ri = df.bbl.map(bi).to_numpy()
    ci = pd.Index(snaps).get_indexer(df.snapshot_date)

    def mat(col):
        m = np.full((nb, 16), np.nan)
        m[ri, ci] = df[col].to_numpy(dtype=float)
        return m

    risk, phat, gap, nacc = mat("risk"), mat("p_hat"), mat("gap_rank"), mat("loud_nacc_share_12m")
    units = df.groupby("bbl").static_unitsres.first().reindex(bbls).to_numpy(dtype=float)
    comp_pu = mat("loud_prob_n_12m") / units[:, None]
    silent, blocked = mat("silent"), mat("access_blocked")
    viol12_m, comp12_m = mat("viol_n_12m"), mat("loud_prob_n_12m")

    codes = {
        "r": percentile_codes(risk), "c": percentile_codes(phat),
        "g": np.where(np.isnan(gap), 999, np.minimum(((np.nan_to_num(gap) + 1) / 2 * 998).astype(int), 998)),
        "a": np.where(np.isnan(nacc), 999, np.minimum((np.nan_to_num(nacc) * 998).astype(int), 998)),
        "m": np.where(np.isnan(comp_pu), 999, np.minimum((np.clip(np.nan_to_num(comp_pu), 0, 2) / 2 * 998).astype(int), 998)),
    }
    strs = {k: [three(v[i]) for i in range(nb)] for k, v in codes.items()}
    sf = ["".join("1" if x == 1 else "0" for x in np.nan_to_num(silent[i])) for i in range(nb)]
    ab = ["".join("1" if x == 1 else "0" for x in np.nan_to_num(blocked[i])) for i in range(nb)]

    # Load Studies 1-4 building enrichment
    enr = load_building_enrichment(bbls)
    hw_arr = enr["bad_winters_3plus"].fillna(0).astype(int).to_numpy()
    oc_arr = enr["open_c"].fillna(0).astype(int).to_numpy()
    omo_arr = enr["omo_usd"].fillna(0.0).to_numpy()
    ev_arr = enr["evict_n"].fillna(0).astype(int).to_numpy()
    sis_arr = enr["sister_vc_pu_22_25"].to_numpy(dtype=float)
    p_bldgs_arr = enr["port_bldgs"].fillna(0).astype(int).to_numpy()
    addr_arr = enr["addr"].fillna("").astype(str).to_numpy()

    # Compact 0..998 codes for new study map layers (999 = no value / unlinked)
    # Open Class C per unit log-scaled (0 = 0, 1..998 = positive)
    oc_pu = oc_arr / np.maximum(units, 1.0)
    oc_code = np.where(oc_arr == 0, 0, np.clip(np.round(np.log1p(oc_pu * 10) / np.log1p(20) * 998), 1, 998).astype(int))
    # OMO spend log-scaled ($0 -> 0, $100k+ -> 998)
    omo_code = np.where(omo_arr <= 0, 0, np.clip(np.round(np.log1p(omo_arr) / np.log1p(150000) * 998), 1, 998).astype(int))
    # Portfolio sister Class C/unit (999 = single-building or unlinked, 0..998 = sister rate)
    pt_code = np.where(np.isnan(sis_arr) | (p_bldgs_arr < 2), 999, np.clip(np.round(np.log1p(sis_arr * 10) / np.log1p(10) * 998), 0, 998).astype(int))
    # Evictions per 100 units (0 = 0, 1..998)
    ev_rate = 100.0 * ev_arr / np.maximum(units, 1.0)
    ev_code = np.where(ev_arr == 0, 0, np.clip(np.round(np.log1p(ev_rate) / np.log1p(35) * 998), 1, 998).astype(int))

    # Guided investigation flags (at latest snapshot idx=15)
    quiet_latest = (np.nan_to_num(viol12_m[:, -1]) == 0) & (np.nan_to_num(comp12_m[:, -1]) == 0)
    qp_flag = (quiet_latest & (~np.isnan(sis_arr)) & (sis_arr >= 0.15) & (p_bldgs_arr >= 2)).astype(int)
    eh_flag = ((ev_arr >= 1) & (oc_arr >= 5)).astype(int)

    print(f"score + study matrices built: {nb:,} lots ({time.time() - t0:.1f}s)", flush=True)

    # ------------------------------------------------------------------ footprints -> NDJSON + search index
    cols = ["the_geom", "bin", "base_bbl", "mappluto_bbl", "height_roof", "construction_year", "last_status_type"]
    fp = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(RAW.glob("part-*.parquet"))], ignore_index=True)
    fp = fp[~fp.last_status_type.isin(DEMOLISHED)].reset_index(drop=True)
    fp["bbl"] = fp.base_bbl.astype(float).astype("int64").astype(str).str.zfill(10)
    alt = fp.mappluto_bbl.astype(float).astype("int64").astype(str).str.zfill(10)
    in_spine = fp.bbl.isin(bi)
    fp.loc[~in_spine & alt.isin(bi), "bbl"] = alt[~in_spine & alt.isin(bi)]
    fp["scored"] = fp.bbl.isin(bi)
    h = pd.to_numeric(fp.height_roof, errors="coerce").fillna(10.0).clip(lower=3.0) * 0.3048
    n_sc = n_ctx = 0
    cd_counts = spine.community_district.value_counts()
    sample_cd = (cd_counts.drop("nan", errors="ignore") - 1100).abs().idxmin()
    sample_rows = []
    district_geoms = {}
    bbl_centroid: dict[str, tuple[float, float]] = {}

    with open(work / "scored.ndjson", "w") as fs, open(work / "context.ndjson", "w") as fc:
        for geom_text, bin_, bbl, hm, yb, scored in zip(fp.the_geom, fp.bin, fp.bbl, h, fp.construction_year, fp.scored):
            g = parse_geom(geom_text)
            g["coordinates"] = round_coords(g["coordinates"])
            if scored:
                i = bi[bbl]
                sp = spine.loc[bbl]
                if bbl not in bbl_centroid:
                    bbl_centroid[bbl] = geom_centroid(g)
                props = {
                    "b": bbl, "n": str(bin_), "bo": sp.borough, "cd": str(sp.community_district),
                    "u": int(units[i]), "yb": int(float(yb)) if pd.notna(yb) and float(yb) > 0 else 0,
                    "h": round(float(hm), 1), "ad": addr_arr[i],
                    "r": strs["r"][i], "c": strs["c"][i], "g": strs["g"][i], "a": strs["a"][i], "m": strs["m"][i],
                    "sf": sf[i], "ab": ab[i],
                    "hw": int(hw_arr[i]), "oc": int(oc_code[i]), "ocn": int(oc_arr[i]),
                    "om": int(omo_code[i]), "omk": int(round(omo_arr[i] / 1000.0)),
                    "pt": int(pt_code[i]), "ev": int(ev_code[i]), "evn": int(ev_arr[i]),
                    "qp": int(qp_flag[i]), "eh": int(eh_flag[i]),
                }
                feat = {"type": "Feature", "geometry": g, "properties": props}
                fs.write(json.dumps(feat, separators=(",", ":")) + "\n")
                n_sc += 1
                district_geoms.setdefault(props["cd"], []).append(g)
                if props["cd"] == sample_cd:
                    sample_rows.append(feat)
            else:
                fc.write(json.dumps({"type": "Feature", "geometry": g, "properties": {"h": round(float(hm), 1)}}, separators=(",", ":")) + "\n")
                n_ctx += 1
    print(f"footprints: {n_sc:,} scored, {n_ctx:,} context ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ facts shards + sharded address search index
    shards = {}
    search_shards: dict[str, list] = {}
    sample_facts = {}
    sample_search = []
    fact_mats = {name: mat(col) for name, (col, _) in FACT_COLS.items()}

    reg_short = {
        "1_never_registered": "unregistered",
        "2_expired_registration": "expired",
        "3_active_corporate_llc": "active_corp",
        "4_active_individual": "active_indiv",
        "5_active_other": "active_other",
    }

    for b in bbls:
        i = bi[b]
        sp = spine.loc[b]
        e = enr.loc[b]
        cd_str = str(sp.community_district)
        addr = str(e["addr"]) if pd.notna(e["addr"]) else ""

        def arr(m, nd):
            return [None if np.isnan(x) else (int(x) if nd == 0 else round(float(x), nd)) for x in m[i]]

        haz = {}
        for k_short, col in [("heat", "h_heat"), ("lead", "h_lead"), ("mold", "h_mold"), ("pests", "h_pests"),
                             ("water", "h_water"), ("fire", "h_fire"), ("doors", "h_doors"), ("walls", "h_walls")]:
            v = int(e[col]) if pd.notna(e[col]) else 0
            if v > 0:
                haz[k_short] = v

        rec = {
            "addr": addr, "zip": str(e["zip"]) if pd.notna(e["zip"]) else "",
            "u": int(units[i]), "yb": int(sp.yearbuilt) if pd.notna(sp.yearbuilt) else None,
            "cls": str(sp.bldgclass), "cd": cd_str, "cd_lbl": CD_NAMES.get(cd_str, f"District {cd_str}"), "bo": sp.borough,
            "risk": arr(risk, 4), "cond": arr(phat, 5), "gap": arr(gap, 3), "nacc": arr(nacc, 2), "complaints_pu": arr(comp_pu, 2),
            "silent": [int(x) for x in np.nan_to_num(silent[i])], "blocked": [int(x) for x in np.nan_to_num(blocked[i])],
            # Building Report Card enrichment (zero PII / zero banned field names)
            "omo_usd": int(round(float(e["omo_usd"]))) if pd.notna(e["omo_usd"]) else 0,
            "omo_n": int(e["omo_n"]) if pd.notna(e["omo_n"]) else 0,
            "hw_w": int(e["bad_winters_3plus"]) if pd.notna(e["bad_winters_3plus"]) else 0,
            "hw_tot": int(e["hw_probs_7w"]) if pd.notna(e["hw_probs_7w"]) else 0,
            "open_c": int(e["open_c"]) if pd.notna(e["open_c"]) else 0,
            "open_c_med_d": int(e["open_c_med_d"]) if pd.notna(e["open_c_med_d"]) else None,
            "ev_tot": int(e["evict_n"]) if pd.notna(e["evict_n"]) else 0,
            "aep_tot": int(e["aep_n"]) if pd.notna(e["aep_n"]) else 0,
            "reg_st": reg_short.get(str(e["reg_group"]), "unregistered"),
            "p_bldgs": int(e["port_bldgs"]) if pd.notna(e["port_bldgs"]) else 0,
            "p_units": int(e["port_units"]) if pd.notna(e["port_units"]) else 0,
            "p_sis_c": round(float(e["sister_vc_pu_22_25"]), 3) if pd.notna(e["sister_vc_pu_22_25"]) else None,
            "peer_pct": int(e["peer_pct"]) if pd.notna(e["peer_pct"]) else 0,
            "haz": haz,
        }
        for name in FACT_COLS:
            rec[name] = arr(fact_mats[name], 0)
        shards.setdefault(b[:5], {})[b] = rec

        if b in bbl_centroid and addr:
            lng, lat = bbl_centroid[b]
            entry = [b, addr, sp.borough, cd_str, int(units[i]), lng, lat]
            search_shards.setdefault(search_shard_key(addr), []).append(entry)
            if cd_str == sample_cd:
                sample_search.append(entry)
        if cd_str == sample_cd:
            sample_facts[b] = rec

    for k, v in shards.items():
        (OUT / "facts" / f"{k}.json").write_text(json.dumps(v, separators=(",", ":")))
    for k, v in search_shards.items():
        (OUT / "search" / f"{k}.json").write_text(json.dumps(v, separators=(",", ":")))
    print(f"facts: {len(shards):,} shards | search: {len(search_shards):,} shards ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ district aggregates + study totals
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    cd_of = np.array([str(spine.loc[b].community_district) for b in bbls])
    bo_of = np.array([spine.loc[b].borough for b in bbls])
    agg = {}
    for cd in sorted(set(cd_of)):
        m = cd_of == cd
        tot_u = float(np.sum(units[m]))
        agg[cd] = {
            "risk": np.nanmean(risk[m], axis=0), "cond": np.nanmean(phat[m], axis=0),
            "gap": np.nanmean(gap[m], axis=0), "nacc": np.nanmean(nacc[m], axis=0),
            "comp": np.nanmean(comp_pu[m], axis=0), "silent": np.nanmean(silent[m], axis=0),
            "n": int(m.sum()),
            "s": {
                "units": int(round(tot_u)),
                "omo_m": round(float(np.sum(omo_arr[m]) / 1e6), 2),
                "omo_pu": round(float(np.sum(omo_arr[m]) / max(tot_u, 1)), 1),
                "heat7_n": int(np.sum(hw_arr[m] >= 6)),
                "heat_avg": round(float(np.mean(hw_arr[m])), 2),
                "open_c_n": int(np.sum(oc_arr[m])),
                "open_c_pu": round(float(np.sum(oc_arr[m]) / max(tot_u, 1)), 3),
                "ev_n": int(np.sum(ev_arr[m])),
                "ev_p1k": round(float(1000.0 * np.sum(ev_arr[m]) / max(tot_u, 1)), 1),
                "sis_avg": round(float(np.nanmean(sis_arr[m])), 3) if np.any(~np.isnan(sis_arr[m])) else 0.0,
                "qp_n": int(np.sum(qp_flag[m])),
                "eh_n": int(np.sum(eh_flag[m])),
            },
        }
    feats = []
    for cd, geoms in district_geoms.items():
        if cd == "nan":
            continue
        poly = unary_union([shape(g).buffer(0.0012) for g in geoms]).buffer(-0.0007).simplify(0.0002)
        c_pt = poly.representative_point()
        a = agg[cd]
        feats.append({"type": "Feature", "geometry": mapping(poly), "properties": {
            "cd": cd, "bo": bo_of[cd_of == cd][0], "nm": CD_NAMES.get(cd, f"District {cd}"),
            "n": a["n"], "cx": round(c_pt.x, 5), "cy": round(c_pt.y, 5),
            "v": {k: [None if np.isnan(x) else round(float(x), 4) for x in a[k]] for k in ("risk", "cond", "gap", "nacc", "comp", "silent")},
            "s": a["s"],
        }})
    (OUT / "districts.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats, "snapshots": [str(pd.Timestamp(s).date()) for s in snaps]}, separators=(",", ":")))
    print(f"districts: {len(feats)} ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ committed sample + studies digest
    sd = OUT / "sample"
    sd.mkdir(exist_ok=True)
    (sd / "buildings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": sample_rows, "snapshots": [str(pd.Timestamp(s).date()) for s in snaps]}, separators=(",", ":")))
    (sd / "facts.json").write_text(json.dumps(sample_facts, separators=(",", ":")))
    (sd / "search.json").write_text(json.dumps(sample_search, separators=(",", ":")))
    print(f"sample: community district {sample_cd}, {len(sample_rows):,} buildings ({time.time() - t0:.0f}s)", flush=True)

    build_studies_digest()

    # ------------------------------------------------------------------ vector tiles
    tipp = shutil.which("tippecanoe")
    if tipp:
        cmd = [tipp, "-o", str(OUT / "buildings.pmtiles"), "--force", "-Z11", "-z16", "--no-tile-size-limit", "--no-feature-limit", "--quiet",
               "-L", json.dumps({"file": str(work / "scored.ndjson"), "layer": "scored", "minzoom": 12, "maxzoom": 16}),
               "-L", json.dumps({"file": str(work / "context.ndjson"), "layer": "context", "minzoom": 14, "maxzoom": 16})]
        subprocess.run(cmd, check=True)
        print(f"buildings.pmtiles: {(OUT / 'buildings.pmtiles').stat().st_size / 1e6:.0f} MB ({time.time() - t0:.0f}s)", flush=True)
    else:
        print("tippecanoe not found: the site falls back to the sample GeoJSON", flush=True)

    (OUT / "meta.json").write_text(json.dumps({
        "snapshots": [str(pd.Timestamp(s).date()) for s in snaps],
        "sample_cd": sample_cd, "scored_buildings": n_sc, "context_buildings": n_ctx,
        "lots": nb, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }))
    print(f"done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
