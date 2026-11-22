"""Study 4: The Eviction-Hazard Paradox.

Tests whether executed marshal evictions systematically co-occur with severe unresolved
housing hazards, rigorously controlling for building size, neighborhood, era, and class:
  4a. Prevalence of executed evictions inside buildings with open Class C hazards, Rent-Impairing
      violations, recent emergency complaints, and active/recent HPD litigation (2019-2025 and
      post-moratorium 2022-2025 separately).
  4b. Coarsened Exact Matching (CEM on borough x community_district x fine unit-size bin x
      era x building_class_letter) + Negative Binomial / Poisson regressions (with CD FE &
      robust/clustered SEs) comparing evicting vs non-evicting buildings of identical size & location.
  4c. Staggered Event-Study Dynamics around First Post-Moratorium Eviction (2022Q3-2024Q3)
      using nycdistress.did.event_study: do Class C violations and tenant complaints rise BEFORE
      an eviction, spike AFTER, or stay chronically elevated?

Outputs:
  reports/studies/study4_*.csv, reports/studies/study4_summary.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

from nycdistress.did import event_study

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT_REP = ROOT / "reports" / "studies"


def main():
    t0 = time.time()
    OUT_REP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(PROC / "marts.duckdb"), read_only=True)
    con.execute("SET threads=6")

    # ------------------------------------------------------------------ 4a. Event-level prevalence (evictions inside hazardous buildings)
    print("[Study 4a] Computing event-level eviction-hazard overlap (2019-2025 & post-moratorium 2022-2025)...", flush=True)
    ev_prev = con.sql(f"""
        WITH ri AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    lpad(boroid, 1, '0') || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                try_cast(left(inspectiondate, 10) AS DATE) AS insp_dt,
                violationstatus,
                try_cast(left(currentstatusdate, 10) AS DATE) AS stat_dt
            FROM read_parquet('{RAW / "hpd_violations/*.parquet"}')
            WHERE rentimpairing = 'Y'
              AND try_cast(left(inspectiondate, 10) AS DATE) >= DATE '2018-01-01'
        ),
        ev AS (
            SELECT e.bbl, e.executed_date, b.borough, b.units_residential,
                   CASE WHEN e.executed_date >= DATE '2022-01-01' THEN 'post_moratorium_2022_2025' ELSE 'pre_or_pandemic_2019_2021' END AS era
            FROM evictions e
            JOIN buildings b USING (bbl)
            WHERE e.executed_date >= DATE '2019-01-01'
        ),
        ctx AS (
            SELECT ev.*,
                (SELECT count(*) FROM hpd_violations v
                 WHERE v.bbl = ev.bbl AND v.violation_class = 'C'
                   AND v.inspection_date <= ev.executed_date
                   AND (v.status = 'Open' OR v.current_status_date > ev.executed_date)) AS open_c_at_ev,
                (SELECT count(*) FROM ri
                 WHERE ri.bbl = ev.bbl AND ri.insp_dt <= ev.executed_date
                   AND (ri.violationstatus = 'Open' OR ri.stat_dt > ev.executed_date)) AS open_ri_at_ev,
                (SELECT count(*) FROM hpd_complaints c
                 WHERE c.bbl = ev.bbl AND c.is_emergency
                   AND c.received_date BETWEEN ev.executed_date - INTERVAL 365 DAY AND ev.executed_date) AS emerg_comp_12m,
                (SELECT count(*) FROM litigations l
                 WHERE l.bbl = ev.bbl
                   AND l.opened_date BETWEEN ev.executed_date - INTERVAL 730 DAY AND ev.executed_date) AS litig_24m,
                (SELECT count(*) FROM litigations l
                 WHERE l.bbl = ev.bbl AND l.harassment_finding IS NOT NULL AND l.harassment_finding != 'No Harassment') AS ever_harassment_finding
            FROM ev
        )
        SELECT era,
               count(*) AS total_evictions,
               round(100.0 * avg(CASE WHEN open_c_at_ev >= 1 THEN 1 ELSE 0 END), 2) AS pct_1plus_open_C,
               round(100.0 * avg(CASE WHEN open_c_at_ev >= 5 THEN 1 ELSE 0 END), 2) AS pct_5plus_open_C,
               round(100.0 * avg(CASE WHEN open_c_at_ev >= 10 THEN 1 ELSE 0 END), 2) AS pct_10plus_open_C,
               round(100.0 * avg(CASE WHEN open_ri_at_ev >= 1 THEN 1 ELSE 0 END), 2) AS pct_1plus_open_rent_impairing,
               round(100.0 * avg(CASE WHEN emerg_comp_12m >= 10 THEN 1 ELSE 0 END), 2) AS pct_10plus_emerg_comp,
               round(100.0 * avg(CASE WHEN litig_24m >= 1 THEN 1 ELSE 0 END), 2) AS pct_recent_litig,
               round(100.0 * avg(CASE WHEN ever_harassment_finding >= 1 THEN 1 ELSE 0 END), 2) AS pct_harassment_finding
        FROM ctx
        GROUP BY 1
        UNION ALL
        SELECT 'all_2019_2025' AS era,
               count(*) AS total_evictions,
               round(100.0 * avg(CASE WHEN open_c_at_ev >= 1 THEN 1 ELSE 0 END), 2),
               round(100.0 * avg(CASE WHEN open_c_at_ev >= 5 THEN 1 ELSE 0 END), 2),
               round(100.0 * avg(CASE WHEN open_c_at_ev >= 10 THEN 1 ELSE 0 END), 2),
               round(100.0 * avg(CASE WHEN open_ri_at_ev >= 1 THEN 1 ELSE 0 END), 2),
               round(100.0 * avg(CASE WHEN emerg_comp_12m >= 10 THEN 1 ELSE 0 END), 2),
               round(100.0 * avg(CASE WHEN litig_24m >= 1 THEN 1 ELSE 0 END), 2),
               round(100.0 * avg(CASE WHEN ever_harassment_finding >= 1 THEN 1 ELSE 0 END), 2)
        FROM ctx
    """).df()
    ev_prev.to_csv(OUT_REP / "study4_eviction_prevalence.csv", index=False)

    # ------------------------------------------------------------------ 4b. CEM + Controlled Poisson/GLM (Post-Moratorium 2022-2025)
    print("[Study 4b] Running CEM & controlled regressions (2022-2025)...", flush=True)
    bdf = con.sql("""
        WITH v AS (
            SELECT bbl,
                   count(*) FILTER (WHERE violation_class = 'C') AS vc,
                   count(*) FILTER (WHERE status = 'Open' AND violation_class = 'C') AS open_c
            FROM hpd_violations WHERE inspection_date >= DATE '2022-01-01' GROUP BY 1
        ),
        o AS (SELECT bbl, sum(award_amount) AS omo_usd FROM omo_charges WHERE created_date >= DATE '2022-01-01' AND award_amount > 0 GROUP BY 1),
        l AS (SELECT bbl, count(*) AS lit_n, count(*) FILTER (WHERE case_type LIKE '%Harrass%' OR case_type LIKE '%Harass%') AS harass_lit FROM litigations WHERE opened_date >= DATE '2022-01-01' GROUP BY 1),
        e AS (SELECT bbl, count(*) AS ev_n FROM evictions WHERE executed_date >= DATE '2022-01-01' GROUP BY 1)
        SELECT b.bbl, b.borough, b.community_district, b.units_residential, b.year_built,
               left(b.building_class, 1) AS bclass_let,
               coalesce(v.vc, 0) AS vc, coalesce(v.open_c, 0) AS open_c,
               coalesce(o.omo_usd, 0.0) AS omo_usd,
               coalesce(l.lit_n, 0) AS lit_n, coalesce(l.harass_lit, 0) AS harass_lit,
               coalesce(e.ev_n, 0) AS ev_n
        FROM buildings b
        LEFT JOIN v USING (bbl) LEFT JOIN o USING (bbl) LEFT JOIN l USING (bbl) LEFT JOIN e USING (bbl)
    """).df()

    bdf["any_ev"] = (bdf["ev_n"] > 0).astype(int)
    bdf["ev_rate_100u"] = 100.0 * bdf["ev_n"] / bdf["units_residential"].clip(lower=1)
    bdf["vc_pu"] = bdf["vc"] / bdf["units_residential"].clip(lower=1)
    bdf["open_c_pu"] = bdf["open_c"] / bdf["units_residential"].clip(lower=1)
    bdf["omo_pu"] = bdf["omo_usd"] / bdf["units_residential"].clip(lower=1)

    # Fine Coarsened Exact Matching on (community_district, fine_units_bin, era_bin, bclass_let)
    bdf["u_fine"] = pd.cut(bdf["units_residential"], bins=[0, 3, 4, 5, 7, 10, 15, 24, 39, 59, 99, 199, 100000])
    bdf["era_bin"] = pd.cut(bdf["year_built"].fillna(0), bins=[-1, 1900, 1929, 1945, 1970, 2000, 2030])
    bdf["cell"] = (bdf["community_district"].astype(str) + "|" + bdf["u_fine"].astype(str)
                   + "|" + bdf["era_bin"].astype(str) + "|" + bdf["bclass_let"].astype(str))
    tc = bdf.groupby("cell")["any_ev"].sum()
    cc = bdf.groupby("cell")["any_ev"].apply(lambda s: (s == 0).sum())
    keep = tc[(tc > 0) & (cc > 0)].index
    m = bdf[bdf["cell"].isin(keep)].copy()
    wmap = (tc / cc).to_dict()
    m["w"] = np.where(m["any_ev"] == 1, 1.0, m["cell"].map(wmap))

    def wm(s, w):
        return float(np.sum(s * w) / np.sum(w))

    cem_rows = []
    rng = np.random.default_rng(7)
    t_mask = m["any_ev"] == 1
    c_mask = m["any_ev"] == 0
    for col in ["units_residential", "vc_pu", "open_c_pu", "omo_pu", "lit_n", "harass_lit"]:
        mt = wm(m.loc[t_mask, col], m.loc[t_mask, "w"])
        mc = wm(m.loc[c_mask, col], m.loc[c_mask, "w"])
        # Quick bootstrap CI on ratio
        t_vals = m.loc[t_mask, col].to_numpy()
        c_vals = m.loc[c_mask, col].to_numpy()
        c_w = m.loc[c_mask, "w"].to_numpy()
        ratios = []
        for _ in range(200):
            ti = rng.integers(0, len(t_vals), len(t_vals))
            ci = rng.integers(0, len(c_vals), len(c_vals))
            num = t_vals[ti].mean()
            den = np.sum(c_vals[ci] * c_w[ci]) / np.sum(c_w[ci])
            ratios.append(num / den if den > 0 else np.nan)
        lo, hi = np.nanpercentile(ratios, [2.5, 97.5])
        cem_rows.append({
            "metric": col,
            "n_evicting_matched": int(t_mask.sum()),
            "n_control_matched": int(c_mask.sum()),
            "evicting_mean": round(mt, 4),
            "matched_control_mean": round(mc, 4),
            "ratio": round(mt / mc, 3) if mc > 0 else np.nan,
            "ratio_ci_lo": round(float(lo), 3),
            "ratio_ci_hi": round(float(hi), 3),
        })
    cem_df = pd.DataFrame(cem_rows)
    cem_df.to_csv(OUT_REP / "study4_cem_comparison.csv", index=False)

    # Controlled Poisson GLM (exposure = units_residential) with CD FE + building class + era + size
    reg_df = bdf[(bdf["year_built"] > 1800) & (bdf["community_district"].notna())].copy()
    X_base = pd.DataFrame({
        "any_ev": reg_df["any_ev"].astype(float),
        "log_ev_rate": np.log1p(reg_df["ev_rate_100u"]),
        "log_units": np.log1p(reg_df["units_residential"].astype(float)),
        "year_dec": (reg_df["year_built"].astype(float) - 1930.0) / 10.0,
    }, index=reg_df.index)
    X_cd = pd.get_dummies(reg_df["community_district"].astype(str), prefix="cd", drop_first=True, dtype=float)
    X_bc = pd.get_dummies(reg_df["bclass_let"].astype(str), prefix="bc", drop_first=True, dtype=float)

    glm_rows = []
    for exp_col in ["any_ev", "log_ev_rate"]:
        X = sm.add_constant(pd.concat([X_base[[exp_col, "log_units", "year_dec"]], X_cd, X_bc], axis=1))
        for tgt in ["vc", "open_c", "lit_n"]:
            fit = sm.GLM(
                reg_df[tgt].astype(float), X,
                family=sm.families.Poisson(),
                offset=np.log(reg_df["units_residential"].clip(lower=1).astype(float)),
            ).fit(cov_type="HC1", maxiter=100)
            b = float(fit.params[exp_col])
            se = float(fit.bse[exp_col])
            glm_rows.append({
                "exposure": exp_col, "outcome": tgt, "n": int(len(reg_df)),
                "irr": round(float(np.exp(b)), 3),
                "ci_lo": round(float(np.exp(b - 1.96 * se)), 3),
                "ci_hi": round(float(np.exp(b + 1.96 * se)), 3),
                "z": round(b / se, 2),
                "p": float(fit.pvalues[exp_col]),
            })
    glm_res = pd.DataFrame(glm_rows)
    glm_res.to_csv(OUT_REP / "study4_glm_regressions.csv", index=False)

    # ------------------------------------------------------------------ 4c. Event-Study Dynamics Around First Post-Moratorium Eviction
    print("[Study 4c] Running staggered event study around first post-moratorium eviction (2022Q3-2024Q3)...", flush=True)
    # Build quarterly panel 2020Q3..2025Q4 (22 quarters: index 0..21)
    q_panel = con.sql("""
        WITH q_dates AS (
            SELECT unnest(generate_series(DATE '2020-07-01', DATE '2025-10-01', INTERVAL 3 MONTH))::DATE AS qstart
        ),
        first_ev AS (
            SELECT bbl, date_trunc('quarter', min(executed_date))::DATE AS first_ev_q
            FROM evictions
            WHERE executed_date >= DATE '2022-01-01'
            GROUP BY 1
        ),
        pre_ev AS (
            SELECT DISTINCT bbl FROM evictions WHERE executed_date BETWEEN DATE '2020-07-01' AND DATE '2021-12-31'
        ),
        base_v19 AS (
            SELECT bbl, count(*) FILTER (WHERE violation_class = 'C') AS vc_19
            FROM hpd_violations WHERE inspection_date BETWEEN DATE '2018-01-01' AND DATE '2019-12-31' GROUP BY 1
        ),
        elig AS (
            SELECT b.bbl, b.borough, b.units_residential, b.year_built,
                   coalesce(bv.vc_19, 0) AS vc_19,
                   fe.first_ev_q
            FROM buildings b
            LEFT JOIN first_ev fe USING (bbl)
            LEFT JOIN base_v19 bv USING (bbl)
            WHERE b.bbl NOT IN (SELECT bbl FROM pre_ev)
              AND (fe.first_ev_q IS NULL OR fe.first_ev_q BETWEEN DATE '2022-07-01' AND DATE '2024-07-01')
        ),
        vc_q AS (
            SELECT bbl, date_trunc('quarter', inspection_date)::DATE AS qstart, count(*) AS vc_n
            FROM hpd_violations
            WHERE violation_class = 'C' AND inspection_date >= DATE '2020-07-01' AND inspection_date < DATE '2026-01-01'
            GROUP BY 1, 2
        ),
        cp_q AS (
            SELECT bbl, date_trunc('quarter', received_date)::DATE AS qstart, count(*) AS cp_n
            FROM hpd_complaints
            WHERE received_date >= DATE '2020-07-01' AND received_date < DATE '2026-01-01'
            GROUP BY 1, 2
        )
        SELECT e.bbl, e.borough, e.units_residential, e.year_built, e.vc_19, e.first_ev_q,
               q.qstart,
               coalesce(vc.vc_n, 0) AS vc_n,
               coalesce(cp.cp_n, 0) AS cp_n
        FROM elig e
        CROSS JOIN q_dates q
        LEFT JOIN vc_q vc ON vc.bbl = e.bbl AND vc.qstart = q.qstart
        LEFT JOIN cp_q cp ON cp.bbl = e.bbl AND cp.qstart = q.qstart
        ORDER BY e.bbl, q.qstart
    """).df()

    q_list = sorted(q_panel["qstart"].unique())
    T = len(q_list)
    q_map = {q: i for i, q in enumerate(q_list)}

    b_meta = q_panel.drop_duplicates("bbl").reset_index(drop=True)
    N = len(b_meta)
    g = np.array([q_map[x] if pd.notna(x) else -1 for x in b_meta["first_ev_q"]], dtype=int)

    # Strata: borough x size_bin x era x pre_vc19_bin
    s_u = pd.cut(b_meta["units_residential"], bins=[0, 5, 19, 49, 100000], labels=False).fillna(0).astype(int)
    s_e = pd.cut(b_meta["year_built"].fillna(0), bins=[-1, 1929, 1960, 2030], labels=False).fillna(0).astype(int)
    s_v = pd.cut(b_meta["vc_19"], bins=[-1, 0, 2, 10, 100000], labels=False).fillna(0).astype(int)
    s_bo = (b_meta["borough"] == "BX").astype(int)
    strata = (((s_bo * 4 + s_u) * 3 + s_e) * 4 + s_v).to_numpy(dtype=int)

    Y_vc_any = (q_panel["vc_n"].to_numpy().reshape(N, T) > 0).astype(float)
    Y_cp_any = (q_panel["cp_n"].to_numpy().reshape(N, T) > 0).astype(float)
    Y_vc_cnt = np.minimum(q_panel["vc_n"].to_numpy().reshape(N, T), np.percentile(q_panel["vc_n"], 99.5)).astype(float)

    ev_rows = []
    ev_summary = []
    for name, Y in [("any_classC_q", Y_vc_any), ("any_complaint_q", Y_cp_any), ("classC_count_q", Y_vc_cnt)]:
        res = event_study(Y, g, pre=6, post=5, control="never", n_boot=250, seed=11, strata=strata)
        for e_t, th, lo, hi in zip(res["events"], res["theta"], res["lo"], res["hi"]):
            ev_rows.append({"outcome": name, "event_q": int(e_t), "theta": round(float(th), 5), "lo": round(float(lo), 5), "hi": round(float(hi), 5)})
        ev_summary.append({
            "outcome": name,
            "n_treated": int((g >= 0).sum()),
            "n_control": int((g < 0).sum()),
            "avg_post": round(res["avg_post"], 5),
            "avg_post_lo": round(res["avg_post_lo"], 5),
            "avg_post_hi": round(res["avg_post_hi"], 5),
            "adj_post": round(res["adj_post"], 5),
            "adj_post_lo": round(res["adj_post_lo"], 5),
            "adj_post_hi": round(res["adj_post_hi"], 5),
            "pre_trend_p": round(res["pre_trend_p"], 5),
        })
    pd.DataFrame(ev_rows).to_csv(OUT_REP / "study4_event_study.csv", index=False)
    ev_sum_df = pd.DataFrame(ev_summary)
    ev_sum_df.to_csv(OUT_REP / "study4_event_study_summary.csv", index=False)

    print("\n=== Study 4a: Evictions Inside Hazardous Buildings ===")
    print(ev_prev.to_string(index=False))
    print("\n=== Study 4b: Coarsened Exact Matched Comparison (Evicting vs Identical-Size Same-CD Non-Evicting) ===")
    print(cem_df.to_string(index=False))
    print("\n=== Study 4b: Controlled Poisson GLM (Offset = Units, CD + Class + Era FE) ===")
    print(glm_res.to_string(index=False))
    print("\n=== Study 4c: Event-Study Around First Post-Moratorium Eviction ===")
    print(ev_sum_df.to_string(index=False))

    (OUT_REP / "study4_summary.json").write_text(json.dumps({
        "study": "Study 4: The Eviction-Hazard Paradox",
        "elapsed_sec": round(time.time() - t0, 1),
    }, indent=2))
    con.close()
    print(f"[Study 4] Done in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
