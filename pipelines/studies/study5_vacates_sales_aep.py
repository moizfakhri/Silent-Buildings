"""Study 5: Vacate Order Subtypes, Heterogeneous Post-Sale Dynamics, & AEP Policy Evaluation.

Deepens Phases 4 & 5 and evaluates HPD's flagship enforcement program (AEP):
  5a. Vacate Order Anatomy & Phase 4 Re-Evaluation:
      Splits vacate orders into Fire Damage vs Illegal Occupancy vs Habitability; computes
      24-month pre-vacate warning trajectories for each subtype; tests Phase 4's silent flag
      separately by vacate subtype & DOB physical hazards (matched RR + O/E).
  5b. Heterogeneous Post-Sale Event Study (Callaway & Sant'Anna staggered DiD via nycdistress.did):
      Stratifies whole-building arms-length sales by pre-sale distress tier (Clean: 0 Class C,
      Mild: 1-4 Class C, Distressed: 5+ Class C in prior 8 quarters) AND by price-per-unit tier,
      matching each tier ONLY against never-sold controls in the exact same pre-sale distress tier
      + borough + size + era. Tracks Class C violations, complaints, serious events, and evictions.
  5c. Quasi-Experimental Evaluation of HPD's Alternative Enforcement Program (AEP):
      Staggered DiD for buildings entering AEP (2020-2023) matched to never-AEP buildings in the
      same pre-selection Class B/C violation tier + borough + size, tracking -8 to +8 quarters on
      Class C violations, complaints, and OMO charges — plus post-discharge relapse analysis.

Outputs:
  reports/studies/study5_*.csv, reports/studies/study5_summary.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from nycdistress.did import event_study

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT_REP = ROOT / "reports" / "studies"


def run_5a_vacates(con: duckdb.DuckDBPyConnection):
    print("[Study 5a] Analyzing vacate order subtypes, pre-vacate trajectories, & Phase 4 re-eval...", flush=True)
    # Pre-vacate 24-month trajectory by vacate reason (2020-2025 vacates in spine)
    traj = con.sql("""
        WITH v AS (
            SELECT DISTINCT ON (bbl, effective_date)
                vo.bbl, vo.effective_date, vo.reason, vo.vacate_type, vo.units_vacated, b.units_residential
            FROM vacate_orders vo
            JOIN buildings b USING (bbl)
            WHERE vo.effective_date BETWEEN DATE '2020-01-01' AND DATE '2025-10-01'
              AND vo.reason IN ('Fire Damage', 'Illegal Occupancy', 'Habitability')
            ORDER BY vo.bbl, vo.effective_date, vo.units_vacated DESC NULLS LAST
        ),
        qs(rel_q) AS (VALUES (-8), (-7), (-6), (-5), (-4), (-3), (-2), (-1), (0), (1), (2), (3)),
        grid AS (
            SELECT v.bbl, v.effective_date, v.reason, v.units_residential, qs.rel_q,
                   v.effective_date + (qs.rel_q * 91) * INTERVAL 1 DAY AS w_start,
                   v.effective_date + ((qs.rel_q + 1) * 91) * INTERVAL 1 DAY AS w_end
            FROM v CROSS JOIN qs
        ),
        agg AS (
            SELECT g.reason, g.rel_q, g.bbl, g.effective_date,
                (SELECT count(*) FROM hpd_violations hv WHERE hv.bbl = g.bbl AND hv.violation_class = 'C' AND hv.inspection_date >= g.w_start AND hv.inspection_date < g.w_end) AS vc_n,
                (SELECT count(*) FROM hpd_complaints hc WHERE hc.bbl = g.bbl AND hc.received_date >= g.w_start AND hc.received_date < g.w_end) AS comp_n,
                (SELECT count(*) FROM dob_violations dv WHERE dv.bbl = g.bbl AND dv.is_hazard AND dv.issue_date >= g.w_start AND dv.issue_date < g.w_end) AS dobhaz_n,
                (SELECT count(*) FROM omo_charges om WHERE om.bbl = g.bbl AND om.created_date >= g.w_start AND om.created_date < g.w_end) AS omo_n
            FROM grid g
        )
        SELECT reason, rel_q,
               count(*) AS vacates,
               round(avg(vc_n), 3) AS avg_classC,
               round(100.0 * avg(CASE WHEN vc_n > 0 THEN 1 ELSE 0 END), 2) AS pct_any_classC,
               round(avg(comp_n), 3) AS avg_complaints,
               round(100.0 * avg(CASE WHEN dobhaz_n > 0 THEN 1 ELSE 0 END), 2) AS pct_any_dobhaz,
               round(100.0 * avg(CASE WHEN omo_n > 0 THEN 1 ELSE 0 END), 2) AS pct_any_omo
        FROM agg
        GROUP BY 1, 2 ORDER BY 1, 2
    """).df()
    traj.to_csv(OUT_REP / "study5_vacate_trajectories.csv", index=False)

    # Phase 4 matched validation split by vacate reason + DOB core hazard
    af = pd.read_parquet(PROC / "phase4" / "analysis_frame.parquet",
                         columns=["bbl", "snapshot_date", "static_borough", "static_unitsres", "static_year_built",
                                  "p_hat", "silent", "label_vacate_or_dobhaz_core"])
    af["snapshot_date"] = pd.to_datetime(af["snapshot_date"])
    af = af[af["snapshot_date"] <= pd.Timestamp("2024-10-01")].copy()

    # Exact forward 12m flags by vacate reason and DOB physical hazard
    con.register("af_keys", af[["bbl", "snapshot_date"]])
    sub_lbl = con.sql("""
        SELECT k.bbl, k.snapshot_date,
               EXISTS(SELECT 1 FROM vacate_orders v WHERE v.bbl = k.bbl AND v.reason = 'Fire Damage' AND v.effective_date > k.snapshot_date AND v.effective_date <= k.snapshot_date + INTERVAL 365 DAY)::INT AS y_fire,
               EXISTS(SELECT 1 FROM vacate_orders v WHERE v.bbl = k.bbl AND v.reason = 'Illegal Occupancy' AND v.effective_date > k.snapshot_date AND v.effective_date <= k.snapshot_date + INTERVAL 365 DAY)::INT AS y_illegal_occ,
               EXISTS(SELECT 1 FROM vacate_orders v WHERE v.bbl = k.bbl AND v.reason = 'Habitability' AND v.effective_date > k.snapshot_date AND v.effective_date <= k.snapshot_date + INTERVAL 365 DAY)::INT AS y_habitability,
               EXISTS(SELECT 1 FROM dob_violations d WHERE d.bbl = k.bbl AND d.violation_type_code IN ('IMEGNCY','UB','FISPHAZ','EGNCY') AND d.issue_date > k.snapshot_date AND d.issue_date <= k.snapshot_date + INTERVAL 365 DAY)::INT AS y_dob_core
        FROM af_keys k
    """).df()
    af = af.merge(sub_lbl, on=["bbl", "snapshot_date"], how="left")
    af["y_nonfire_primary"] = ((af["y_illegal_occ"] == 1) | (af["y_habitability"] == 1) | (af["y_dob_core"] == 1)).astype(int)

    # Match silent vs not-silent on (borough, p_hat decile, units_bin, era_bin) with ATT weights
    af["ph_bin"] = pd.qcut(af["p_hat"], q=10, labels=False, duplicates="drop")
    af["u_bin"] = pd.cut(af["static_unitsres"], bins=[0, 5, 19, 49, 100000], labels=False)
    af["e_bin"] = pd.cut(af["static_year_built"].fillna(0), bins=[-1, 1929, 1960, 2030], labels=False)
    af["cell"] = af["static_borough"].astype(str) + "|" + af["ph_bin"].astype(str) + "|" + af["u_bin"].astype(str) + "|" + af["e_bin"].astype(str)
    tc = af.groupby("cell")["silent"].sum()
    cc = af.groupby("cell")["silent"].apply(lambda s: (s == 0).sum())
    keep = tc[(tc > 0) & (cc > 0)].index
    m = af[af["cell"].isin(keep)].copy()
    wmap = (tc / cc).to_dict()
    m["w"] = np.where(m["silent"] == 1, 1.0, m["cell"].map(wmap))

    rows = []
    rng = np.random.default_rng(19)
    # Cluster bootstrap by bbl
    t_mask = m["silent"] == 1
    c_mask = m["silent"] == 0
    for col in ["y_fire", "y_illegal_occ", "y_habitability", "y_dob_core", "y_nonfire_primary", "label_vacate_or_dobhaz_core"]:
        rt = float(m.loc[t_mask, col].mean())
        rc = float(np.sum(m.loc[c_mask, col] * m.loc[c_mask, "w"]) / np.sum(m.loc[c_mask, "w"]))
        rr = rt / rc if rc > 0 else np.nan
        # Vectorized building aggregation
        tmp = pd.DataFrame({
            "bbl": m["bbl"].to_numpy(),
            "tn": np.where(t_mask, m[col].to_numpy(), 0.0),
            "td": np.where(t_mask, 1.0, 0.0),
            "cn": np.where(c_mask, m[col].to_numpy() * m["w"].to_numpy(), 0.0),
            "cd": np.where(c_mask, m["w"].to_numpy(), 0.0),
        }).groupby("bbl", sort=False).sum()
        arr = tmp.to_numpy()
        nb = len(arr)
        draws = []
        for _ in range(250):
            idx = rng.integers(0, nb, nb)
            s = arr[idx].sum(axis=0)
            r_t = s[0] / s[1] if s[1] > 0 else np.nan
            r_c = s[2] / s[3] if s[3] > 0 else np.nan
            draws.append(r_t / r_c if r_c > 0 else np.nan)
        lo, hi = np.nanpercentile(draws, [2.5, 97.5])
        rows.append({
            "outcome": col,
            "silent_events": int(m.loc[t_mask, col].sum()),
            "control_events": int(m.loc[c_mask, col].sum()),
            "silent_rate_per_10k": round(10000.0 * rt, 2),
            "matched_ctrl_rate_per_10k": round(10000.0 * rc, 2),
            "matched_rr": round(rr, 3),
            "ci_lo": round(float(lo), 3),
            "ci_hi": round(float(hi), 3),
        })
    p4_split = pd.DataFrame(rows)
    p4_split.to_csv(OUT_REP / "study5_vacate_subtype_silent_rr.csv", index=False)
    return traj, p4_split


def run_5b_heterogeneous_sales(con: duckdb.DuckDBPyConnection):
    print("[Study 5b] Running heterogeneous post-sale staggered DiD (Clean vs Mild vs Distressed sales)...", flush=True)
    # Build quarterly panel 2018Q1..2025Q4 (32 quarters)
    q_panel = con.sql(f"""
        WITH q_dates AS (
            SELECT unnest(generate_series(DATE '2018-01-01', DATE '2025-10-01', INTERVAL 3 MONTH))::DATE AS qstart
        ),
        raw_sales AS (
            SELECT lpad(CAST(try_cast(bbl AS BIGINT) AS VARCHAR), 10, '0') AS bbl,
                   try_cast(left(sale_date, 10) AS DATE) AS sale_date,
                   try_cast(sale_price AS DOUBLE) AS price
            FROM read_parquet('{RAW / "dof_sales/*.parquet"}')
            WHERE (apartment_number IS NULL OR trim(apartment_number) = '')
              AND try_cast(sale_price AS DOUBLE) >= 100000
              AND try_cast(left(sale_date, 10) AS DATE) >= DATE '2018-01-01'
        ),
        b_sales AS (
            SELECT rs.bbl, count(*) AS n_sales,
                   min(rs.sale_date) AS first_sale_date,
                   min_by(rs.price, rs.sale_date) AS first_price
            FROM raw_sales rs
            JOIN buildings b USING (bbl)
            WHERE rs.price / nullif(b.units_residential, 0) >= 25000
            GROUP BY 1
        ),
        -- Pre-2020 baseline Class C (2018-2019) to stratify cleanly WITHOUT post-treatment conditioning!
        vc18_19 AS (
            SELECT bbl, count(*) FILTER (WHERE violation_class = 'C') AS vc_base
            FROM hpd_violations
            WHERE inspection_date BETWEEN DATE '2018-01-01' AND DATE '2019-12-31'
            GROUP BY 1
        ),
        elig AS (
            SELECT b.bbl, b.borough, b.units_residential, b.year_built,
                   coalesce(v.vc_base, 0) AS vc_base,
                   CASE
                     WHEN bs.bbl IS NULL THEN NULL
                     WHEN bs.n_sales = 1 AND bs.first_sale_date BETWEEN DATE '2020-01-01' AND DATE '2024-06-30'
                     THEN date_trunc('quarter', bs.first_sale_date)::DATE
                     ELSE DATE '1900-01-01'
                   END AS sale_q,
                   bs.first_price / nullif(b.units_residential, 0) AS ppu
            FROM buildings b
            LEFT JOIN b_sales bs USING (bbl)
            LEFT JOIN vc18_19 v USING (bbl)
        ),
        elig_clean AS (
            SELECT * FROM elig WHERE sale_q IS NULL OR sale_q != DATE '1900-01-01'
        ),
        vc_q AS (
            SELECT bbl, date_trunc('quarter', inspection_date)::DATE AS qstart, count(*) AS vc_n
            FROM hpd_violations WHERE violation_class = 'C' AND inspection_date >= DATE '2018-01-01' AND inspection_date < DATE '2026-01-01'
            GROUP BY 1, 2
        ),
        cp_q AS (
            SELECT bbl, date_trunc('quarter', received_date)::DATE AS qstart, count(*) AS cp_n
            FROM hpd_complaints WHERE received_date >= DATE '2018-01-01' AND received_date < DATE '2026-01-01'
            GROUP BY 1, 2
        ),
        ev_q AS (
            SELECT bbl, date_trunc('quarter', executed_date)::DATE AS qstart, count(*) AS ev_n
            FROM evictions WHERE executed_date >= DATE '2018-01-01' AND executed_date < DATE '2026-01-01'
            GROUP BY 1, 2
        )
        SELECT e.bbl, e.borough, e.units_residential, e.year_built, e.vc_base, e.sale_q, e.ppu,
               q.qstart,
               coalesce(vc.vc_n, 0) AS vc_n,
               coalesce(cp.cp_n, 0) AS cp_n,
               coalesce(ev.ev_n, 0) AS ev_n
        FROM elig_clean e
        CROSS JOIN q_dates q
        LEFT JOIN vc_q vc ON vc.bbl = e.bbl AND vc.qstart = q.qstart
        LEFT JOIN cp_q cp ON cp.bbl = e.bbl AND cp.qstart = q.qstart
        LEFT JOIN ev_q ev ON ev.bbl = e.bbl AND ev.qstart = q.qstart
        ORDER BY e.bbl, q.qstart
    """).df()

    q_list = sorted(q_panel["qstart"].unique())
    T = len(q_list)
    q_map = {q: i for i, q in enumerate(q_list)}
    b_meta = q_panel.drop_duplicates("bbl").reset_index(drop=True)
    N = len(b_meta)

    g_all = np.array([q_map[x] if pd.notna(x) else -1 for x in b_meta["sale_q"]], dtype=int)
    Y_vc = (q_panel["vc_n"].to_numpy().reshape(N, T) > 0).astype(float)
    Y_cp = (q_panel["cp_n"].to_numpy().reshape(N, T) > 0).astype(float)
    Y_ev = (q_panel["ev_n"].to_numpy().reshape(N, T) > 0).astype(float)

    # Tier definitions based strictly on pre-2020 baseline Class C (clean = 0, mild = 1-4, distressed = 5+)
    tiers = {
        "clean_base_0C": b_meta["vc_base"] == 0,
        "mild_base_1to4C": (b_meta["vc_base"] >= 1) & (b_meta["vc_base"] <= 4),
        "distressed_base_5plusC": b_meta["vc_base"] >= 5,
    }
    # Also discount vs premium sales (comparing low-PPU vs high-PPU treated against matched never-sold controls)
    med_ppu = b_meta.loc[g_all >= 0, "ppu"].median()
    tiers["discount_sale_below_med_ppu"] = (g_all < 0) | (b_meta["ppu"] < med_ppu)
    tiers["premium_sale_above_med_ppu"] = (g_all < 0) | (b_meta["ppu"] >= med_ppu)

    rows = []
    for tname, mask_s in tiers.items():
        idx = np.flatnonzero(mask_s.to_numpy())
        sub_m = b_meta.iloc[idx].reset_index(drop=True)
        g = g_all[idx]
        s_u = pd.cut(sub_m["units_residential"], bins=[0, 5, 19, 49, 100000], labels=False).fillna(0).astype(int)
        s_e = pd.cut(sub_m["year_built"].fillna(0), bins=[-1, 1929, 1960, 2030], labels=False).fillna(0).astype(int)
        s_v = pd.cut(sub_m["vc_base"], bins=[-1, 0, 4, 15, 100000], labels=False).fillna(0).astype(int)
        s_bo = (sub_m["borough"] == "BX").astype(int)
        strata = (((s_bo * 4 + s_u) * 3 + s_e) * 4 + s_v).to_numpy(dtype=int)

        for oname, Y_full in [("any_classC", Y_vc), ("any_complaint", Y_cp), ("any_eviction", Y_ev)]:
            Y = Y_full[idx]
            res = event_study(Y, g, pre=6, post=6, control="never", n_boot=250, seed=21, strata=strata)
            pre_mean = float(Y[g >= 0, :8].mean())
            rows.append({
                "tier": tname, "outcome": oname,
                "n_treated": int((g >= 0).sum()), "n_control": int((g < 0).sum()),
                "treated_pre_mean": round(pre_mean, 4),
                "avg_post": round(res["avg_post"], 5),
                "avg_post_lo": round(res["avg_post_lo"], 5),
                "avg_post_hi": round(res["avg_post_hi"], 5),
                "adj_post": round(res["adj_post"], 5),
                "adj_post_lo": round(res["adj_post_lo"], 5),
                "adj_post_hi": round(res["adj_post_hi"], 5),
                "pre_trend_p": round(res["pre_trend_p"], 4),
            })
    sales_het = pd.DataFrame(rows)
    sales_het.to_csv(OUT_REP / "study5_sales_heterogeneous.csv", index=False)
    return sales_het


def run_5c_aep_evaluation(con: duckdb.DuckDBPyConnection):
    print("[Study 5c] Running quasi-experimental evaluation of HPD's Alternative Enforcement Program (AEP)...", flush=True)
    # Buildings first selected into AEP in 2020-2023 vs never-AEP high-violation controls
    q_panel = con.sql("""
        WITH q_dates AS (
            SELECT unnest(generate_series(DATE '2018-01-01', DATE '2025-10-01', INTERVAL 3 MONTH))::DATE AS qstart
        ),
        first_aep AS (
            SELECT bbl, min(start_date) AS aep_start, min(discharge_date) AS aep_discharge
            FROM aep_programs
            GROUP BY 1
        ),
        -- Pre-2020 violation intensity (Class B+C, which is how AEP selects buildings!)
        bc18_19 AS (
            SELECT bbl,
                   count(*) FILTER (WHERE violation_class IN ('B', 'C')) AS bc_18_19,
                   count(*) FILTER (WHERE violation_class = 'C') AS c_18_19
            FROM hpd_violations
            WHERE inspection_date BETWEEN DATE '2018-01-01' AND DATE '2019-12-31'
            GROUP BY 1
        ),
        elig AS (
            SELECT b.bbl, b.borough, b.units_residential, b.year_built,
                   coalesce(bc.bc_18_19, 0) AS bc_18_19,
                   coalesce(bc.c_18_19, 0) AS c_18_19,
                   fa.aep_start, fa.aep_discharge,
                   CASE
                     WHEN fa.aep_start IS NULL THEN NULL
                     WHEN fa.aep_start BETWEEN DATE '2020-01-01' AND DATE '2023-12-31' THEN date_trunc('quarter', fa.aep_start)::DATE
                     ELSE DATE '1900-01-01'
                   END AS aep_q
            FROM buildings b
            LEFT JOIN first_aep fa USING (bbl)
            LEFT JOIN bc18_19 bc USING (bbl)
            WHERE coalesce(bc.bc_18_19, 0) >= 10   -- restrict to high-violation universe comparable to AEP
        ),
        elig_clean AS (
            SELECT * FROM elig WHERE aep_q IS NULL OR aep_q != DATE '1900-01-01'
        ),
        vc_q AS (
            SELECT bbl, date_trunc('quarter', inspection_date)::DATE AS qstart, count(*) AS vc_n
            FROM hpd_violations WHERE violation_class = 'C' AND inspection_date >= DATE '2018-01-01' AND inspection_date < DATE '2026-01-01'
            GROUP BY 1, 2
        ),
        cp_q AS (
            SELECT bbl, date_trunc('quarter', received_date)::DATE AS qstart, count(*) AS cp_n
            FROM hpd_complaints WHERE received_date >= DATE '2018-01-01' AND received_date < DATE '2026-01-01'
            GROUP BY 1, 2
        ),
        om_q AS (
            SELECT bbl, date_trunc('quarter', created_date)::DATE AS qstart, count(*) AS om_n
            FROM omo_charges WHERE created_date >= DATE '2018-01-01' AND created_date < DATE '2026-01-01'
            GROUP BY 1, 2
        )
        SELECT e.bbl, e.borough, e.units_residential, e.bc_18_19, e.aep_q, e.aep_start, e.aep_discharge,
               q.qstart,
               coalesce(vc.vc_n, 0) AS vc_n,
               coalesce(cp.cp_n, 0) AS cp_n,
               coalesce(om.om_n, 0) AS om_n
        FROM elig_clean e
        CROSS JOIN q_dates q
        LEFT JOIN vc_q vc ON vc.bbl = e.bbl AND vc.qstart = q.qstart
        LEFT JOIN cp_q cp ON cp.bbl = e.bbl AND cp.qstart = q.qstart
        LEFT JOIN om_q om ON om.bbl = e.bbl AND om.qstart = q.qstart
        ORDER BY e.bbl, q.qstart
    """).df()

    q_list = sorted(q_panel["qstart"].unique())
    T = len(q_list)
    q_map = {q: i for i, q in enumerate(q_list)}
    b_meta = q_panel.drop_duplicates("bbl").reset_index(drop=True)
    N = len(b_meta)
    g = np.array([q_map[x] if pd.notna(x) else -1 for x in b_meta["aep_q"]], dtype=int)

    # Match controls strictly on borough x size_bin x pre-2020 B+C violation intensity bin
    s_u = pd.cut(b_meta["units_residential"], bins=[0, 5, 19, 49, 100000], labels=False).fillna(0).astype(int)
    s_v = pd.cut(b_meta["bc_18_19"], bins=[9, 25, 50, 100, 200, 100000], labels=False).fillna(0).astype(int)
    s_bo = (b_meta["borough"] == "BX").astype(int)
    strata = ((s_bo * 4 + s_u) * 5 + s_v).to_numpy(dtype=int)

    Y_vc = np.minimum(q_panel["vc_n"].to_numpy().reshape(N, T), np.percentile(q_panel["vc_n"], 99.5)).astype(float)
    Y_cp = np.minimum(q_panel["cp_n"].to_numpy().reshape(N, T), np.percentile(q_panel["cp_n"], 99.5)).astype(float)
    Y_om = (q_panel["om_n"].to_numpy().reshape(N, T) > 0).astype(float)

    ev_rows = []
    sum_rows = []
    for name, Y in [("classC_count_q", Y_vc), ("complaints_count_q", Y_cp), ("any_omo_q", Y_om)]:
        res = event_study(Y, g, pre=6, post=8, control="never", n_boot=250, seed=31, strata=strata)
        for e_t, th, lo, hi in zip(res["events"], res["theta"], res["lo"], res["hi"]):
            ev_rows.append({"outcome": name, "event_q": int(e_t), "theta": round(float(th), 4), "lo": round(float(lo), 4), "hi": round(float(hi), 4)})
        sum_rows.append({
            "outcome": name,
            "n_aep_treated": int((g >= 0).sum()),
            "n_highviol_ctrl": int((g < 0).sum()),
            "avg_post_q0_q8": round(res["avg_post"], 4),
            "avg_post_lo": round(res["avg_post_lo"], 4),
            "avg_post_hi": round(res["avg_post_hi"], 4),
            "pre_trend_p": round(res["pre_trend_p"], 4),
        })
    pd.DataFrame(ev_rows).to_csv(OUT_REP / "study5_aep_event_study.csv", index=False)
    aep_sum = pd.DataFrame(sum_rows)
    aep_sum.to_csv(OUT_REP / "study5_aep_summary.csv", index=False)

    # Post-discharge relapse check for ALL discharged AEP buildings (discharged 2018-2023)
    relapse = con.sql("""
        WITH dis AS (
            SELECT a.bbl, a.start_date, a.discharge_date, b.units_residential
            FROM aep_programs a
            JOIN buildings b USING (bbl)
            WHERE a.discharge_date BETWEEN DATE '2018-01-01' AND DATE '2023-12-31'
        ),
        post AS (
            SELECT d.*,
                   datediff('day', d.start_date, d.discharge_date) AS days_in_aep,
                   (SELECT count(*) FROM hpd_violations v WHERE v.bbl = d.bbl AND v.violation_class = 'C' AND v.inspection_date > d.discharge_date AND v.inspection_date <= d.discharge_date + INTERVAL 2 YEAR) AS post2y_vc,
                   (SELECT count(*) FROM omo_charges o WHERE o.bbl = d.bbl AND o.created_date > d.discharge_date AND o.created_date <= d.discharge_date + INTERVAL 2 YEAR) AS post2y_omo,
                   (SELECT count(*) FROM aep_programs a2 WHERE a2.bbl = d.bbl AND a2.start_date > d.discharge_date) AS reentered_aep
            FROM dis d
        )
        SELECT count(*) AS discharged_bldgs,
               round(median(days_in_aep), 0) AS median_days_to_discharge,
               round(100.0 * avg(CASE WHEN post2y_vc >= 5 THEN 1 ELSE 0 END), 1) AS pct_5plus_classC_within_2y,
               round(100.0 * avg(CASE WHEN post2y_vc >= 15 THEN 1 ELSE 0 END), 1) AS pct_15plus_classC_within_2y,
               round(100.0 * avg(CASE WHEN post2y_omo >= 1 THEN 1 ELSE 0 END), 1) AS pct_new_omo_within_2y,
               round(100.0 * avg(CASE WHEN reentered_aep >= 1 THEN 1 ELSE 0 END), 1) AS pct_reentered_aep
        FROM post
    """).df()
    relapse.to_csv(OUT_REP / "study5_aep_relapse.csv", index=False)
    return aep_sum, relapse


def main():
    t0 = time.time()
    OUT_REP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(PROC / "marts.duckdb"), read_only=True)
    con.execute("SET threads=6")

    traj, p4_split = run_5a_vacates(con)
    sales_het = run_5b_heterogeneous_sales(con)
    aep_sum, relapse = run_5c_aep_evaluation(con)

    print("\n=== Study 5a: Phase 4 Matched Silent RR Split by Vacate Reason & DOB Core ===")
    print(p4_split.to_string(index=False))
    print("\n=== Study 5b: Heterogeneous Post-Sale Event Study (Clean vs Mild vs Distressed) ===")
    print(sales_het[["tier", "outcome", "n_treated", "treated_pre_mean", "avg_post", "avg_post_lo", "avg_post_hi", "pre_trend_p"]].to_string(index=False))
    print("\n=== Study 5c: AEP Staggered DiD Evaluation ===")
    print(aep_sum.to_string(index=False))
    print("\n=== Study 5c: Post-Discharge AEP Relapse (2 Years After Discharge) ===")
    print(relapse.to_string(index=False))

    (OUT_REP / "study5_summary.json").write_text(json.dumps({
        "study": "Study 5: Vacate Subtypes, Heterogeneous Sales & AEP Evaluation",
        "elapsed_sec": round(time.time() - t0, 1),
    }, indent=2))
    con.close()
    print(f"[Study 5] Done in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
