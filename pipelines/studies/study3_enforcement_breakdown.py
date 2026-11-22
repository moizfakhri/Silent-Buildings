"""Study 3: The 'Zombie Class C' Enforcement Breakdown & Complaint-to-Fix Funnel.

Quantifies:
  3a. End-to-end Housing Enforcement Funnel (2019-2025 BX+BK spine):
      complaints -> closed vs open -> no-access vs inspected/condition-not-found vs violation issued
      -> certification (on-time / late / invalid / false) -> closed/dismissed vs still open.
  3b. Proper Kaplan-Meier Survival Analysis of Violation Time-to-Closure (handling right-censoring!):
      by violation class (A, B, C, I), Rent-Impairing flag, hazard category (parsed from NOV text:
      Heat/Hot Water, Lead Paint, Mold/Mildew, Pests/Rodents, Water Leak/Plumbing, Doors/Locks,
      Fire/Smoke/CO, Structural/Plaster), and borough.
  3c. False & Invalid Certifications: prevalence, concentration, and matched post-event comparison
      (do buildings caught with FALSE CERTIFICATION show higher future Class C violations, OMO spend,
      and litigations than matched buildings with identical prior Class C counts?).
  3d. No-Access Closure Dissection: exact status_description categories, winter heat-season surge,
      category breakdown, and anonymous vs named complaints.

Outputs:
  reports/studies/study3_*.csv, reports/studies/study3_summary.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT_REP = ROOT / "reports" / "studies"

CENSOR_DATE = "2026-11-11"


def kaplan_meier_summary(durations: np.ndarray, events: np.ndarray) -> dict:
    """Fast vectorized Kaplan-Meier estimator (durations in days >= 0, events=1 if closed, 0 if censored)."""
    n = len(durations)
    if n == 0:
        return {}
    # Bin at integer days for speed across millions of violations
    d_int = np.clip(np.rint(durations).astype(np.int32), 0, 4000)
    max_d = int(d_int.max())
    ev_cnt = np.bincount(d_int, weights=events, minlength=max_d + 1)
    tot_cnt = np.bincount(d_int, minlength=max_d + 1)
    at_risk = n - np.concatenate(([0], np.cumsum(tot_cnt[:-1])))
    with np.errstate(divide="ignore", invalid="ignore"):
        haz = np.where(at_risk > 0, ev_cnt / at_risk, 0.0)
    surv = np.cumprod(1.0 - haz)

    def s_at(day):
        return float(surv[min(day, max_d)])

    # Median survival time (first day where S(t) <= 0.5)
    below50 = np.flatnonzero(surv <= 0.5)
    med = int(below50[0]) if len(below50) else None
    below25 = np.flatnonzero(surv <= 0.25)
    p75 = int(below25[0]) if len(below25) else None

    return {
        "n": int(n),
        "n_closed": int(events.sum()),
        "n_open_censored": int((1 - events).sum()),
        "pct_open_raw": round(100.0 * (1 - events.mean()), 2),
        "km_median_days": med,
        "km_p75_days": p75,
        "km_still_open_30d_pct": round(100.0 * s_at(30), 2),
        "km_still_open_90d_pct": round(100.0 * s_at(90), 2),
        "km_still_open_180d_pct": round(100.0 * s_at(180), 2),
        "km_still_open_1yr_pct": round(100.0 * s_at(365), 2),
        "km_still_open_2yr_pct": round(100.0 * s_at(730), 2),
        "km_still_open_3yr_pct": round(100.0 * s_at(1095), 2),
    }


def main():
    t0 = time.time()
    OUT_REP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=6")

    spine_sql = f"SELECT bbl, borough, community_district, unitsres AS units_residential FROM read_parquet('{PROC / 'spine.parquet'}')"

    # ------------------------------------------------------------------ 3a. Enforcement Funnel & No-Access Dissection
    print("[Study 3a] Building Complaint-to-Fix Enforcement Funnel & No-Access Dissection...", flush=True)
    comp_funnel = con.sql(f"""
        WITH sp AS ({spine_sql}),
        c AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    CASE borough WHEN 'BRONX' THEN '2' WHEN 'BROOKLYN' THEN '3' END || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                problem_status,
                major_category,
                complaint_anonymous_flag AS anon,
                try_cast(left(received_date, 10) AS DATE) AS recv_dt,
                try_cast(left(problem_status_date, 10) AS DATE) AS stat_dt,
                lower(coalesce(status_description, '')) AS sd
            FROM read_parquet('{RAW / "hpd_complaints/*.parquet"}')
            WHERE try_cast(left(received_date, 10) AS DATE) BETWEEN DATE '2019-01-01' AND DATE '2025-12-31'
        ),
        j AS (
            SELECT c.*, sp.borough,
                   datediff('day', c.recv_dt, c.stat_dt) AS lag_days,
                   CASE
                     WHEN c.problem_status != 'CLOSE' THEN 'open_complaint'
                     WHEN c.sd LIKE '%violations were issued%' THEN 'violation_issued'
                     WHEN c.sd LIKE '%not able to gain access%' OR c.sd LIKE '%unable to gain access%' THEN 'no_access'
                     WHEN c.sd LIKE '%no violations were issued%' THEN 'inspected_no_violation'
                     WHEN c.sd LIKE '%was not warranted%' OR c.sd LIKE '%duplicate%' THEN 'not_warranted_or_dup'
                     WHEN c.sd LIKE '%heat or hot water was restored%' OR c.sd LIKE '%restored%' THEN 'restored_before_inspect'
                     WHEN c.sd LIKE '%advised the tenant%' OR c.sd LIKE '%mailed%' OR c.sd LIKE '%notice%' THEN 'notice_only'
                     ELSE 'other_closed'
                   END AS outcome_cat
            FROM c JOIN sp USING (bbl)
        )
        SELECT outcome_cat,
               count(*) AS problems,
               round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
               round(median(lag_days) FILTER (WHERE lag_days >= 0 AND lag_days < 365), 1) AS median_days
        FROM j
        GROUP BY 1 ORDER BY 2 DESC
    """).df()
    comp_funnel.to_csv(OUT_REP / "study3_complaint_funnel.csv", index=False)

    # Detailed status_description breakdown for no-access closures (2 attempts vs 1 attempt vs season)
    nacc_detail = con.sql(f"""
        WITH sp AS ({spine_sql}),
        c AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    CASE borough WHEN 'BRONX' THEN '2' WHEN 'BROOKLYN' THEN '3' END || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                try_cast(left(received_date, 10) AS DATE) AS recv_dt,
                try_cast(left(problem_status_date, 10) AS DATE) AS stat_dt,
                status_description,
                major_category,
                complaint_anonymous_flag AS anon
            FROM read_parquet('{RAW / "hpd_complaints/*.parquet"}')
            WHERE problem_status = 'CLOSE'
              AND try_cast(left(received_date, 10) AS DATE) BETWEEN DATE '2019-01-01' AND DATE '2025-12-31'
        )
        SELECT
            CASE
              WHEN lower(status_description) LIKE '%attempted to inspect%' AND lower(status_description) LIKE '%more than once%' THEN 'no_access_multiple_attempts'
              WHEN lower(status_description) LIKE '%not able to gain access%' OR lower(status_description) LIKE '%unable to gain access%' THEN 'no_access_other'
              ELSE 'accessed_or_other'
            END AS access_type,
            count(*) AS n,
            round(median(datediff('day', recv_dt, stat_dt)) FILTER (WHERE stat_dt >= recv_dt), 1) AS median_lag_days,
            round(quantile_cont(datediff('day', recv_dt, stat_dt), 0.75) FILTER (WHERE stat_dt >= recv_dt), 1) AS p75_lag_days
        FROM c JOIN sp USING (bbl)
        GROUP BY 1 ORDER BY 2 DESC
    """).df()
    nacc_detail.to_csv(OUT_REP / "study3_no_access_mechanics.csv", index=False)

    # Monthly seasonality of complaint volume, violation-yield rate, and no-access rate
    monthly = con.sql(f"""
        WITH sp AS ({spine_sql}),
        c AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    CASE borough WHEN 'BRONX' THEN '2' WHEN 'BROOKLYN' THEN '3' END || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                month(try_cast(left(received_date, 10) AS DATE)) AS mo,
                lower(coalesce(status_description, '')) AS sd
            FROM read_parquet('{RAW / "hpd_complaints/*.parquet"}')
            WHERE problem_status = 'CLOSE'
              AND try_cast(left(received_date, 10) AS DATE) BETWEEN DATE '2019-01-01' AND DATE '2025-12-31'
        )
        SELECT mo AS month,
               count(*) AS closed_problems,
               round(100.0 * avg(CASE WHEN sd LIKE '%not able to gain access%' OR sd LIKE '%unable to gain access%' THEN 1 ELSE 0 END), 2) AS pct_no_access,
               round(100.0 * avg(CASE WHEN sd LIKE '%violations were issued%' THEN 1 ELSE 0 END), 2) AS pct_violation_issued,
               round(100.0 * avg(CASE WHEN sd LIKE '%restored%' THEN 1 ELSE 0 END), 2) AS pct_restored
        FROM c JOIN sp USING (bbl)
        GROUP BY 1 ORDER BY 1
    """).df()
    monthly.to_csv(OUT_REP / "study3_complaint_seasonality.csv", index=False)

    # ------------------------------------------------------------------ 3b. Kaplan-Meier Survival of Violations
    print("[Study 3b] Running Kaplan-Meier survival analysis on 4.4M HPD violations...", flush=True)
    vdf = con.sql(f"""
        WITH sp AS ({spine_sql}),
        v AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    lpad(boroid, 1, '0') || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                class AS vclass,
                rentimpairing,
                violationstatus,
                currentstatus,
                try_cast(left(inspectiondate, 10) AS DATE) AS insp_dt,
                try_cast(left(currentstatusdate, 10) AS DATE) AS stat_dt,
                lower(coalesce(novdescription, '')) AS descr
            FROM read_parquet('{RAW / "hpd_violations/*.parquet"}')
            WHERE try_cast(left(inspectiondate, 10) AS DATE) BETWEEN DATE '2018-01-01' AND DATE '2025-12-31'
        )
        SELECT sp.borough, v.vclass, v.rentimpairing, v.violationstatus, v.currentstatus,
               CASE
                 WHEN v.descr LIKE '%heat%' OR v.descr LIKE '%hot water%' THEN 'heat_hot_water'
                 WHEN v.descr LIKE '%lead-based%' OR v.descr LIKE '%lead paint%' THEN 'lead_paint'
                 WHEN v.descr LIKE '%mold%' OR v.descr LIKE '%mildew%' THEN 'mold'
                 WHEN v.descr LIKE '%mice%' OR v.descr LIKE '%roach%' OR v.descr LIKE '%rat%' OR v.descr LIKE '%vermin%' OR v.descr LIKE '%pest%' OR v.descr LIKE '%bedbug%' THEN 'pests_vermin'
                 WHEN v.descr LIKE '%leak%' OR v.descr LIKE '%plumb%' OR v.descr LIKE '%water%' OR v.descr LIKE '%pipe%' OR v.descr LIKE '%toilet%' OR v.descr LIKE '%sink%' THEN 'water_plumbing'
                 WHEN v.descr LIKE '%smoke%' OR v.descr LIKE '%carbon monoxide%' OR v.descr LIKE '%fire%' OR v.descr LIKE '%sprinkler%' OR v.descr LIKE '%self-closing%' THEN 'fire_safety'
                 WHEN v.descr LIKE '%lock%' OR v.descr LIKE '%door%' OR v.descr LIKE '%window%' OR v.descr LIKE '%intercom%' THEN 'doors_windows_locks'
                 WHEN v.descr LIKE '%plaster%' OR v.descr LIKE '%paint%' OR v.descr LIKE '%ceiling%' OR v.descr LIKE '%wall%' OR v.descr LIKE '%floor%' THEN 'walls_ceilings_floors'
                 ELSE 'other'
               END AS hazard_cat,
               CASE
                 WHEN v.violationstatus = 'Close' AND v.stat_dt >= v.insp_dt AND v.stat_dt <= DATE '{CENSOR_DATE}'
                 THEN datediff('day', v.insp_dt, v.stat_dt)
                 WHEN v.violationstatus = 'Open'
                 THEN datediff('day', v.insp_dt, DATE '{CENSOR_DATE}')
                 ELSE NULL
               END AS dur_days,
               CASE WHEN v.violationstatus = 'Close' THEN 1 ELSE 0 END AS is_closed
        FROM v JOIN sp USING (bbl)
    """).df()
    vdf = vdf.dropna(subset=["dur_days"]).copy()

    km_rows = []
    # By violation class
    for vc, grp in vdf.groupby("vclass"):
        km_rows.append({"group_type": "violation_class", "group": vc, **kaplan_meier_summary(grp["dur_days"].to_numpy(), grp["is_closed"].to_numpy())})
    # Class C x Rent-Impairing
    c_only = vdf[vdf["vclass"] == "C"]
    for ri, grp in c_only.groupby("rentimpairing"):
        km_rows.append({"group_type": "classC_rent_impairing", "group": f"C_rentimpairing_{ri}", **kaplan_meier_summary(grp["dur_days"].to_numpy(), grp["is_closed"].to_numpy())})
    # Class C x Borough
    for bo, grp in c_only.groupby("borough"):
        km_rows.append({"group_type": "classC_borough", "group": bo, **kaplan_meier_summary(grp["dur_days"].to_numpy(), grp["is_closed"].to_numpy())})
    # Class C x Hazard Category
    for hc, grp in c_only.groupby("hazard_cat"):
        km_rows.append({"group_type": "classC_hazard_category", "group": hc, **kaplan_meier_summary(grp["dur_days"].to_numpy(), grp["is_closed"].to_numpy())})
    km_df = pd.DataFrame(km_rows)
    km_df.to_csv(OUT_REP / "study3_km_survival.csv", index=False)

    # ------------------------------------------------------------------ 3c. False / Invalid Certifications Matched Outcome Check
    print("[Study 3c] Testing outcomes after FALSE / INVALID CERTIFICATION...", flush=True)
    con.execute(f"ATTACH '{PROC / 'marts.duckdb'}' AS m (READ_ONLY)")
    fc_df = con.sql(f"""
        WITH sp AS ({spine_sql}),
        v AS (
            SELECT
                coalesce(
                    CASE WHEN length(trim(bbl)) = 10 THEN trim(bbl) END,
                    lpad(boroid, 1, '0') || lpad(block, 5, '0') || lpad(lot, 4, '0')
                ) AS bbl,
                class AS vclass,
                currentstatus,
                try_cast(left(inspectiondate, 10) AS DATE) AS insp_dt
            FROM read_parquet('{RAW / "hpd_violations/*.parquet"}')
            WHERE try_cast(left(inspectiondate, 10) AS DATE) BETWEEN DATE '2021-01-01' AND DATE '2025-12-31'
        ),
        pre AS (
            SELECT bbl,
                   count(*) FILTER (WHERE vclass = 'C') AS pre_vc,
                   count(*) FILTER (WHERE currentstatus = 'FALSE CERTIFICATION') AS pre_false_cert,
                   count(*) FILTER (WHERE currentstatus = 'INVALID CERTIFICATION') AS pre_invalid_cert
            FROM v WHERE insp_dt BETWEEN DATE '2021-01-01' AND DATE '2023-12-31'
            GROUP BY 1
        ),
        post AS (
            SELECT bbl, count(*) FILTER (WHERE vclass = 'C') AS post_vc
            FROM v WHERE insp_dt BETWEEN DATE '2024-01-01' AND DATE '2025-12-31'
            GROUP BY 1
        ),
        omo_post AS (
            SELECT bbl, sum(award_amount) AS post_omo_usd
            FROM m.omo_charges
            WHERE created_date BETWEEN DATE '2024-01-01' AND DATE '2025-12-31' AND award_amount > 0
            GROUP BY 1
        ),
        lit_post AS (
            SELECT bbl, count(*) AS post_litig
            FROM m.litigations
            WHERE opened_date BETWEEN DATE '2024-01-01' AND DATE '2025-12-31'
            GROUP BY 1
        )
        SELECT sp.bbl, sp.borough, sp.units_residential,
               pre.pre_vc, pre.pre_false_cert, pre.pre_invalid_cert,
               coalesce(post.post_vc, 0) AS post_vc,
               coalesce(o.post_omo_usd, 0.0) AS post_omo_usd,
               coalesce(l.post_litig, 0) AS post_litig
        FROM sp
        JOIN pre USING (bbl)
        LEFT JOIN post USING (bbl)
        LEFT JOIN omo_post o USING (bbl)
        LEFT JOIN lit_post l USING (bbl)
        WHERE pre.pre_vc >= 5
    """).df()
    con.execute("DETACH m")

    # Coarsened Exact Matching on (borough, units_bin, pre_vc_bin) for buildings with false_cert > 0 vs == 0
    fc_df["treated"] = (fc_df["pre_false_cert"] > 0).astype(int)
    fc_df["u_bin"] = pd.cut(fc_df["units_residential"], bins=[0, 5, 19, 49, 99, 10000])
    fc_df["vc_bin"] = pd.qcut(fc_df["pre_vc"], q=10, duplicates="drop")
    fc_df["cell"] = fc_df["borough"].astype(str) + "|" + fc_df["u_bin"].astype(str) + "|" + fc_df["vc_bin"].astype(str)
    t_cnt = fc_df.groupby("cell")["treated"].sum()
    c_cnt = fc_df.groupby("cell")["treated"].apply(lambda s: (s == 0).sum())
    keep_cells = t_cnt[(t_cnt > 0) & (c_cnt > 0)].index
    m_df = fc_df[fc_df["cell"].isin(keep_cells)].copy()
    # ATT weights: treated = 1, control = n_t / n_c
    w_map = (t_cnt / c_cnt).to_dict()
    m_df["w"] = np.where(m_df["treated"] == 1, 1.0, m_df["cell"].map(w_map))

    def wmean(s, w):
        return float(np.sum(s * w) / np.sum(w))

    fc_res = []
    for col in ["pre_vc", "units_residential", "post_vc", "post_omo_usd", "post_litig"]:
        mt = wmean(m_df.loc[m_df["treated"] == 1, col], m_df.loc[m_df["treated"] == 1, "w"])
        mc = wmean(m_df.loc[m_df["treated"] == 0, col], m_df.loc[m_df["treated"] == 0, "w"])
        fc_res.append({
            "metric": col,
            "n_treated": int((m_df["treated"] == 1).sum()),
            "n_control": int((m_df["treated"] == 0).sum()),
            "treated_mean": round(mt, 2),
            "matched_control_mean": round(mc, 2),
            "ratio": round(mt / mc, 3) if mc > 0 else np.nan,
        })
    fc_res_df = pd.DataFrame(fc_res)
    fc_res_df.to_csv(OUT_REP / "study3_false_certification_matched.csv", index=False)

    print("\n=== Study 3a: Complaint-to-Fix Funnel (2019-2025) ===")
    print(comp_funnel.to_string(index=False))
    print("\n=== Study 3b: Kaplan-Meier Survival (Handling Right-Censoring!) ===")
    print(km_df[["group_type", "group", "n", "km_median_days", "km_still_open_90d_pct", "km_still_open_1yr_pct", "km_still_open_3yr_pct"]].to_string(index=False))
    print("\n=== Study 3c: Matched Post-Event Outcomes After FALSE CERTIFICATION ===")
    print(fc_res_df.to_string(index=False))

    summary = {
        "study": "Study 3: Zombie Class C Enforcement Breakdown & Funnel",
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (OUT_REP / "study3_summary.json").write_text(json.dumps(summary, indent=2))
    con.close()
    print(f"[Study 3] Done in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
