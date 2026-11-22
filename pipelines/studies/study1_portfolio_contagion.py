"""Study 1: Landlord Portfolio Networks & Cross-Building Contagion.

Builds an anonymized building-to-portfolio linkage from HPD Multiple Dwelling Registrations
and Registration Contacts (using SHA-256 hashed normalized business addresses — zero personal
or corporate names are stored or emitted). Tests:
  1a. Registration status & portfolio-size gradients across all 101,749 spine buildings.
  1b. Cross-building contagion regressions (CD + snapshot FE, portfolio-clustered SEs) on
      completely quiet buildings (0 complaints & 0 violations in prior 12m), Phase 4 silent
      buildings, and all multi-building portfolio lots — plus shuffled-portfolio placebos,
      stricter portfolio-size caps, and a stable-ownership (never-sold) sensitivity check.
  1c. Strictly temporal walk-forward LightGBM lift test (all 4 folds, 12m purge gap)
      comparing baseline features vs +leave-one-out portfolio features across all slices
      (all, quiet, zero_viol, clean_record) and the Phase 4 condition model.

Outputs:
  reports/studies/study1_*.csv, reports/studies/study1_summary.json
  data/processed/studies/portfolio_building_summary.parquet (gitignored, anonymized)
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

from nycdistress.metrics import average_precision, roc_auc
from nycdistress.modeling import CONDITION_SETS, SLICES, fit_lgb, load_frame, predict_lgb, rows
from nycdistress.splits import make_folds

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT_REP = ROOT / "reports" / "studies"
OUT_PROC = PROC / "studies"


def hash_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def build_portfolio_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Link each spine BBL to registration status, owner type, and anonymized portfolio IDs."""
    q = f"""
    WITH spine AS (
        SELECT bbl, borough, community_district, unitsres AS units_residential, yearbuilt AS year_built, bldgclass
        FROM read_parquet('{PROC / "spine.parquet"}')
    ),
    regs AS (
        SELECT DISTINCT ON (registrationid)
            registrationid,
            lpad(boroid, 1, '0') || lpad(block, 5, '0') || lpad(lot, 4, '0') AS bbl,
            try_cast(left(lastregistrationdate, 10) AS DATE) AS last_reg_date,
            try_cast(left(registrationenddate, 10) AS DATE) AS reg_end_date
        FROM read_parquet('{RAW / "hpd_registrations/*.parquet"}')
        ORDER BY registrationid, lastregistrationdate DESC NULLS LAST
    ),
    bldg_reg AS (
        SELECT DISTINCT ON (r.bbl) r.bbl, r.registrationid, r.last_reg_date, r.reg_end_date
        FROM regs r
        JOIN spine s USING (bbl)
        ORDER BY r.bbl, r.last_reg_date DESC NULLS LAST
    ),
    contacts AS (
        SELECT DISTINCT ON (registrationcontactid)
            registrationid,
            type,
            upper(regexp_replace(
                trim(coalesce(businesshousenumber, '') || ' ' || coalesce(businessstreetname, '') || ' ' || left(coalesce(businesszip, ''), 5)),
                '\\s+', ' ', 'g'
            )) AS biz_addr
        FROM read_parquet('{RAW / "hpd_reg_contacts/*.parquet"}')
        WHERE type IN ('HeadOfficer', 'CorporateOwner', 'Agent', 'IndividualOwner', 'JointOwner')
        ORDER BY registrationcontactid
    ),
    clean_contacts AS (
        SELECT registrationid, type,
               CASE
                 WHEN length(biz_addr) >= 10
                  AND biz_addr NOT LIKE '%PO BOX%'
                  AND biz_addr NOT LIKE '%P O BOX%'
                  AND biz_addr NOT LIKE '%P.O.%'
                  AND biz_addr NOT LIKE '%BOX %'
                 THEN biz_addr
               END AS clean_addr
        FROM contacts
    ),
    per_bldg AS (
        SELECT
            s.bbl, s.borough, s.community_district, s.units_residential, s.year_built, s.bldgclass,
            br.registrationid IS NOT NULL AS is_registered,
            br.last_reg_date,
            br.reg_end_date,
            coalesce(br.reg_end_date >= DATE '2026-01-01', FALSE) AS reg_active_2026,
            coalesce(bool_or(c.type = 'CorporateOwner'), FALSE) AS has_corp_owner,
            coalesce(bool_or(c.type IN ('IndividualOwner', 'JointOwner')), FALSE) AS has_indiv_owner,
            max(CASE WHEN c.type = 'HeadOfficer' THEN c.clean_addr END) AS ho_addr,
            max(CASE WHEN c.type = 'CorporateOwner' THEN c.clean_addr END) AS corp_addr,
            max(CASE WHEN c.type = 'Agent' THEN c.clean_addr END) AS agent_addr
        FROM spine s
        LEFT JOIN bldg_reg br USING (bbl)
        LEFT JOIN clean_contacts c USING (registrationid)
        GROUP BY 1,2,3,4,5,6,7,8,9,10
    )
    SELECT *,
           coalesce(ho_addr, corp_addr, agent_addr) AS raw_port_key,
           ho_addr AS raw_ho_key
    FROM per_bldg
    """
    df = con.sql(q).df()
    # Anonymize keys immediately; raw address strings are never saved anywhere
    df["portfolio_id"] = df["raw_port_key"].map(lambda x: hash_id(x) if pd.notna(x) and x else None)
    df["ho_portfolio_id"] = df["raw_ho_key"].map(lambda x: hash_id(x) if pd.notna(x) and x else None)
    df = df.drop(columns=["raw_port_key", "raw_ho_key", "ho_addr", "corp_addr", "agent_addr"])

    # Portfolio sizes
    p_sizes = df.dropna(subset=["portfolio_id"]).groupby("portfolio_id").agg(
        port_bldgs=("bbl", "count"),
        port_units=("units_residential", "sum"),
    )
    df = df.merge(p_sizes, on="portfolio_id", how="left")
    df["port_bldgs"] = df["port_bldgs"].fillna(0).astype(int)
    df["port_units"] = df["port_units"].fillna(0).astype(int)

    ho_sizes = df.dropna(subset=["ho_portfolio_id"]).groupby("ho_portfolio_id")["bbl"].count().rename("ho_port_bldgs")
    df = df.merge(ho_sizes, on="ho_portfolio_id", how="left")
    df["ho_port_bldgs"] = df["ho_port_bldgs"].fillna(0).astype(int)

    # Mark buildings with any arms-length whole-building DOF sale 2018-2025 (for stable-ownership sensitivity)
    sold = con.sql(f"""
        SELECT DISTINCT lpad(CAST(try_cast(bbl AS BIGINT) AS VARCHAR), 10, '0') AS bbl
        FROM read_parquet('{RAW / "dof_sales/*.parquet"}')
        WHERE try_cast(sale_price AS DOUBLE) >= 100000
          AND (apartment_number IS NULL OR trim(apartment_number) = '')
          AND try_cast(left(sale_date, 10) AS DATE) >= DATE '2018-01-01'
    """).df()["bbl"]
    df["had_sale_2018_2025"] = df["bbl"].isin(set(sold))
    return df


def analysis_1a_gradients(con: duckdb.DuckDBPyConnection, port: pd.DataFrame):
    """Registration status and portfolio-size gradients (2022-2025 outcomes)."""
    con.register("port_tbl", port)
    marts = str(PROC / "marts.duckdb")
    con.execute(f"ATTACH '{marts}' AS m (READ_ONLY)")

    bstats = con.sql("""
        WITH v AS (
            SELECT bbl,
                   count(*) FILTER (WHERE violation_class = 'C') AS vc,
                   count(*) FILTER (WHERE status = 'Open' AND violation_class = 'C') AS open_c,
                   count(*) AS v_all
            FROM m.hpd_violations WHERE inspection_date >= DATE '2022-01-01' GROUP BY 1
        ),
        o AS (
            SELECT bbl, count(*) AS omo_n, sum(award_amount) AS omo_usd
            FROM m.omo_charges WHERE created_date >= DATE '2022-01-01' AND award_amount > 0 GROUP BY 1
        ),
        e AS (SELECT bbl, count(*) AS ev_n FROM m.evictions WHERE executed_date >= DATE '2022-01-01' GROUP BY 1),
        l AS (SELECT bbl, count(*) AS lit_n FROM m.litigations WHERE opened_date >= DATE '2022-01-01' GROUP BY 1),
        c AS (SELECT bbl, count(*) AS comp_n FROM m.hpd_complaints WHERE received_date >= DATE '2022-01-01' GROUP BY 1)
        SELECT p.*,
               coalesce(v.vc, 0) AS vc, coalesce(v.open_c, 0) AS open_c, coalesce(v.v_all, 0) AS v_all,
               coalesce(o.omo_n, 0) AS omo_n, coalesce(o.omo_usd, 0.0) AS omo_usd,
               coalesce(e.ev_n, 0) AS ev_n, coalesce(l.lit_n, 0) AS lit_n, coalesce(c.comp_n, 0) AS comp_n
        FROM port_tbl p
        LEFT JOIN v USING (bbl) LEFT JOIN o USING (bbl)
        LEFT JOIN e USING (bbl) LEFT JOIN l USING (bbl) LEFT JOIN c USING (bbl)
    """).df()

    def reg_cat(r):
        if not r["is_registered"]:
            return "1_never_registered"
        if not r["reg_active_2026"]:
            return "2_expired_registration"
        if r["has_corp_owner"]:
            return "3_active_corporate_llc"
        if r["has_indiv_owner"]:
            return "4_active_individual"
        return "5_active_other"

    bstats["reg_group"] = bstats.apply(reg_cat, axis=1)

    def summarize(df_in, grp_col):
        g = df_in.groupby(grp_col, dropna=False).agg(
            buildings=("bbl", "count"),
            units=("units_residential", "sum"),
            avg_units=("units_residential", "mean"),
            vc=("vc", "sum"),
            open_c=("open_c", "sum"),
            omo_usd=("omo_usd", "sum"),
            ev_n=("ev_n", "sum"),
            lit_n=("lit_n", "sum"),
            comp_n=("comp_n", "sum"),
        ).reset_index()
        g["classC_per_unit"] = (g["vc"] / g["units"]).round(4)
        g["openC_per_unit"] = (g["open_c"] / g["units"]).round(4)
        g["omo_usd_per_unit"] = (g["omo_usd"] / g["units"]).round(2)
        g["omo_M"] = (g["omo_usd"] / 1e6).round(2)
        g["evict_per_1k_units"] = (1000.0 * g["ev_n"] / g["units"]).round(2)
        g["litig_per_1k_units"] = (1000.0 * g["lit_n"] / g["units"]).round(2)
        g["comp_per_unit"] = (g["comp_n"] / g["units"]).round(3)
        g["avg_units"] = g["avg_units"].round(1)
        return g

    reg_tbl = summarize(bstats, "reg_group")
    reg_tbl.to_csv(OUT_REP / "study1_registration_groups.csv", index=False)

    # Portfolio size buckets (for buildings with a linked portfolio_id)
    linked = bstats[bstats["portfolio_id"].notna()].copy()
    linked["port_bucket"] = pd.cut(
        linked["port_bldgs"],
        bins=[0, 1, 4, 19, 49, 199, 100000],
        labels=["1_single", "2_2to4", "3_5to19", "4_20to49", "5_50to199", "6_200plus"],
    )
    port_tbl = summarize(linked, "port_bucket")
    port_tbl.to_csv(OUT_REP / "study1_portfolio_size_gradient.csv", index=False)

    # Portfolio-level concentration (multi-building + single-building portfolios capped <= 200 to exclude huge generic agents)
    p_agg = linked[linked["port_bldgs"] <= 200].groupby("portfolio_id").agg(
        bldgs=("bbl", "count"),
        units=("units_residential", "sum"),
        vc=("vc", "sum"),
        open_c=("open_c", "sum"),
        omo_usd=("omo_usd", "sum"),
        ev_n=("ev_n", "sum"),
        lit_n=("lit_n", "sum"),
    )
    conc_rows = []
    n_ports = len(p_agg)
    tot_units = p_agg["units"].sum()
    for metric in ["vc", "open_c", "omo_usd", "ev_n", "lit_n"]:
        s = p_agg.sort_values(metric, ascending=False)
        tot = s[metric].sum()
        for pct in [0.005, 0.01, 0.05]:
            k = max(1, int(round(n_ports * pct)))
            top = s.iloc[:k]
            conc_rows.append({
                "metric": metric,
                "top_portfolio_pct": pct * 100,
                "n_portfolios": k,
                "share_of_metric_pct": round(100.0 * top[metric].sum() / tot, 2),
                "share_of_units_pct": round(100.0 * top["units"].sum() / tot_units, 2),
                "share_of_buildings_pct": round(100.0 * top["bldgs"].sum() / p_agg["bldgs"].sum(), 2),
                "excess_ratio_vs_units": round((top[metric].sum() / tot) / (top["units"].sum() / tot_units), 2),
            })
    conc_df = pd.DataFrame(conc_rows)
    conc_df.to_csv(OUT_REP / "study1_portfolio_concentration.csv", index=False)

    # Save anonymized building-level portfolio summary for map / report card
    # Compute 2022-2025 leave-one-out sister Class C rate per unit for the latest view
    p_tot_vc = linked.groupby("portfolio_id")["vc"].transform("sum")
    p_tot_u = linked.groupby("portfolio_id")["units_residential"].transform("sum")
    p_tot_ev = linked.groupby("portfolio_id")["ev_n"].transform("sum")
    p_tot_omo = linked.groupby("portfolio_id")["omo_usd"].transform("sum")
    denom = (p_tot_u - linked["units_residential"]).replace(0, np.nan)
    linked["sister_vc_pu_22_25"] = ((p_tot_vc - linked["vc"]) / denom).where(linked["port_bldgs"] <= 200)
    linked["sister_ev_p1k_22_25"] = (1000.0 * (p_tot_ev - linked["ev_n"]) / denom).where(linked["port_bldgs"] <= 200)
    linked["sister_omo_pu_22_25"] = ((p_tot_omo - linked["omo_usd"]) / denom).where(linked["port_bldgs"] <= 200)

    out_cols = ["bbl", "portfolio_id", "port_bldgs", "port_units", "reg_group", "had_sale_2018_2025"]
    summary = bstats[out_cols].merge(
        linked[["bbl", "sister_vc_pu_22_25", "sister_ev_p1k_22_25", "sister_omo_pu_22_25"]],
        on="bbl", how="left"
    )
    OUT_PROC.mkdir(parents=True, exist_ok=True)
    summary.to_parquet(OUT_PROC / "portfolio_building_summary.parquet", index=False)
    con.execute("DETACH m")
    return reg_tbl, port_tbl, conc_df


def add_asof_portfolio_features(df: pd.DataFrame, port: pd.DataFrame, max_port_size: int = 200, id_col: str = "portfolio_id") -> pd.DataFrame:
    """Attach strictly as-of leave-one-out portfolio features at every (bbl, snapshot_date).

    Because every input column (`viol_c_n_12m`, `loud_prob_n_12m`, etc.) is already strictly as-of t,
    the leave-one-out portfolio sum at snapshot t uses ONLY events dated <= t.
    """
    p_map = port[["bbl", id_col, "port_bldgs", "is_registered", "reg_end_date", "has_corp_owner", "had_sale_2018_2025"]].copy()
    p_map = p_map.rename(columns={id_col: "_pid"})
    if id_col == "ho_portfolio_id":
        p_map["_psize"] = port["ho_port_bldgs"].to_numpy()
    else:
        p_map["_psize"] = p_map["port_bldgs"].to_numpy()

    m = df[["bbl", "snapshot_date", "static_unitsres", "viol_c_n_12m", "viol_n_12m", "viol_open_c_n",
            "loud_prob_n_12m", "prior_omo_n", "prior_litig_n", "evict_n_12m"]].merge(p_map, on="bbl", how="left")

    valid_multi = m["_pid"].notna() & (m["_psize"] >= 2) & (m["_psize"] <= max_port_size)
    m["_valid_pid"] = np.where(valid_multi, m["_pid"], None)

    out = pd.DataFrame(index=df.index)
    out["port_bldgs_log"] = np.log1p(m["_psize"].fillna(0).clip(upper=max_port_size)).astype("float32")
    out["port_is_multi"] = valid_multi.astype("float32")
    out["port_is_registered"] = m["is_registered"].fillna(False).astype("float32")
    out["port_has_corp"] = m["has_corp_owner"].fillna(False).astype("float32")
    # Strictly as-of registration expiration check relative to snapshot_date
    reg_end = pd.to_datetime(m["reg_end_date"])
    out["port_reg_expired_asof"] = ((m["is_registered"].fillna(False)) & (reg_end.notna()) & (reg_end < m["snapshot_date"])).astype("float32")

    # Compute leave-one-out rates per unit across sister buildings within each (snapshot_date, _valid_pid)
    sub = m.loc[valid_multi, ["snapshot_date", "_valid_pid", "static_unitsres", "viol_c_n_12m", "viol_n_12m",
                              "viol_open_c_n", "loud_prob_n_12m", "prior_omo_n", "prior_litig_n", "evict_n_12m"]].copy()
    grp = sub.groupby(["snapshot_date", "_valid_pid"], sort=False)
    tot_u = grp["static_unitsres"].transform("sum") - sub["static_unitsres"]
    tot_u = tot_u.replace(0, np.nan)

    feat_specs = [
        ("port_sister_vc12_pu", "viol_c_n_12m"),
        ("port_sister_v12_pu", "viol_n_12m"),
        ("port_sister_openc_pu", "viol_open_c_n"),
        ("port_sister_comp12_pu", "loud_prob_n_12m"),
        ("port_sister_omo_pu", "prior_omo_n"),
        ("port_sister_litig_pu", "prior_litig_n"),
        ("port_sister_evict12_pu", "evict_n_12m"),
    ]
    for fname, src in feat_specs:
        tot_x = grp[src].transform("sum") - sub[src].fillna(0)
        vals = (tot_x / tot_u).astype("float32")
        s = pd.Series(np.nan, index=df.index, dtype="float32")
        s.loc[valid_multi] = vals.to_numpy()
        out[fname] = s

    out["_pid"] = m["_valid_pid"].to_numpy()
    out["_had_sale"] = m["had_sale_2018_2025"].fillna(False).to_numpy()
    return out


def run_contagion_logit(sub: pd.DataFrame, target: str, exposure: str = "log_sister_vc") -> dict:
    """Clustered logistic regression with Community District + Snapshot FE, clustered by portfolio."""
    d = sub.dropna(subset=[exposure, target, "static_unitsres", "static_year_built", "community_district", "_pid"]).copy()
    d = d[d["static_year_built"] > 1800]
    if len(d) < 200 or d[target].sum() < 20:
        return {"n": len(d), "events": int(d[target].sum()), "or": np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "z": np.nan, "p": np.nan}

    X_num = pd.DataFrame({
        exposure: d[exposure].astype(float),
        "log_units": np.log1p(d["static_unitsres"].astype(float)),
        "year_built_dec": (d["static_year_built"].astype(float) - 1930.0) / 10.0,
        "port_bldgs_log": d["port_bldgs_log"].astype(float),
    }, index=d.index)
    X_cd = pd.get_dummies(d["community_district"].astype(str), prefix="cd", drop_first=True, dtype=float)
    X_sn = pd.get_dummies(d["snapshot_date"].astype(str), prefix="sn", drop_first=True, dtype=float)
    X = sm.add_constant(pd.concat([X_num, X_cd, X_sn], axis=1))
    y = d[target].astype(float)

    res = sm.Logit(y, X).fit(disp=False, maxiter=100, cov_type="cluster", cov_kwds={"groups": d["_pid"]})
    b = float(res.params[exposure])
    se = float(res.bse[exposure])
    return {
        "n": int(len(d)),
        "portfolios": int(d["_pid"].nunique()),
        "events": int(y.sum()),
        "base_rate_pct": round(100.0 * float(y.mean()), 2),
        "beta": round(b, 4),
        "se": round(se, 4),
        "or": round(float(np.exp(b)), 3),
        "ci_lo": round(float(np.exp(b - 1.96 * se)), 3),
        "ci_hi": round(float(np.exp(b + 1.96 * se)), 3),
        "z": round(b / se, 2),
        "p": float(res.pvalues[exposure]),
    }


def analysis_1b_contagion(df: pd.DataFrame, port: pd.DataFrame, pfeats: pd.DataFrame):
    """Run controlled portfolio contagion tests + placebos + sensitivity checks."""
    # Attach next-12m Class C label from marts/features (shift? No — compute directly from hpd_violations!)
    con = duckdb.connect(str(PROC / "marts.duckdb"), read_only=True)
    # Build exact next-12m Class C violation indicator for the 4 annual Jan-1 snapshots (2022..2025) to avoid overlapping 12m windows!
    # Wait: using non-overlapping annual snapshots (2021-01-01, 2022-01-01, 2023-01-01, 2024-01-01) keeps observations clean and fast!
    annual_snaps = pd.to_datetime(["2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01"])
    ann_mask = df["snapshot_date"].isin(annual_snaps)
    ann = pd.concat([df.loc[ann_mask, ["bbl", "snapshot_date", "community_district", "static_borough",
                                       "static_unitsres", "static_year_built", "viol_n_12m", "viol_c_n_12m",
                                       "viol_open_n", "loud_prob_n_12m", "label_serious_any",
                                       "label_vacate_or_dobhaz_core", "label_omo", "label_litigation"]],
                     pfeats.loc[ann_mask]], axis=1)

    # Exact forward 12m Class C label from hpd_violations: (t, t + 12m]
    vc_next = con.sql("""
        WITH snaps(snapshot_date) AS (
            VALUES (DATE '2021-01-01'), (DATE '2022-01-01'), (DATE '2023-01-01'), (DATE '2024-01-01')
        )
        SELECT v.bbl, s.snapshot_date, count(*) AS next_vc_12m
        FROM snaps s
        JOIN hpd_violations v
          ON v.violation_class = 'C'
         AND v.inspection_date > s.snapshot_date
         AND v.inspection_date <= s.snapshot_date + INTERVAL 1 YEAR
        GROUP BY 1, 2
    """).df()
    vc_next["snapshot_date"] = pd.to_datetime(vc_next["snapshot_date"])
    ann = ann.merge(vc_next, on=["bbl", "snapshot_date"], how="left")
    ann["label_class_c_any"] = (ann["next_vc_12m"].fillna(0) > 0).astype(int)

    # Merge Phase 4 silent flag for 2022..2024 snapshots
    af = pd.read_parquet(PROC / "phase4" / "analysis_frame.parquet", columns=["bbl", "snapshot_date", "silent"])
    af["snapshot_date"] = pd.to_datetime(af["snapshot_date"])
    ann = ann.merge(af, on=["bbl", "snapshot_date"], how="left")

    ann["log_sister_vc"] = np.log1p(ann["port_sister_vc12_pu"] * 10.0)
    # Standardize exposure for clean per-SD interpretation too
    sd_exp = ann["log_sister_vc"].std()
    ann["z_sister_vc"] = ann["log_sister_vc"] / sd_exp

    # Shuffled-portfolio placebo: permute sister_vc within (snapshot_date, borough, port_size_bin)
    rng = np.random.default_rng(42)
    ann["pbin"] = pd.cut(ann["port_bldgs_log"], bins=[0, 1.5, 2.5, 3.5, 10])
    ann["z_sister_placebo"] = ann["z_sister_vc"].copy()
    valid_idx = ann["z_sister_vc"].notna()
    for _, grp_idx in ann.loc[valid_idx].groupby(["snapshot_date", "static_borough", "pbin"], observed=True).groups.items():
        vals = ann.loc[grp_idx, "z_sister_vc"].to_numpy().copy()
        rng.shuffle(vals)
        ann.loc[grp_idx, "z_sister_placebo"] = vals

    # Descriptive tier table for completely quiet buildings (0 complaints & 0 violations in prior 12m)
    quiet = ann[(ann["viol_n_12m"] == 0) & (ann["loud_prob_n_12m"] == 0) & (ann["port_sister_vc12_pu"].notna())].copy()
    quiet["sister_tier"] = pd.cut(
        quiet["port_sister_vc12_pu"],
        bins=[-0.001, 0.0, 0.05, 0.15, 0.35, 1000],
        labels=["0_clean_0", "1_low_lt0.05", "2_med_0.05_0.15", "3_high_0.15_0.35", "4_severe_0.35plus"],
    )
    tier_tbl = quiet.groupby("sister_tier", observed=True).agg(
        rows=("bbl", "count"),
        avg_units=("static_unitsres", "mean"),
        pct_class_c_next12m=("label_class_c_any", lambda x: round(100 * x.mean(), 2)),
        pct_serious_next12m=("label_serious_any", lambda x: round(100 * x.mean(), 2)),
        pct_omo_next12m=("label_omo", lambda x: round(100 * x.mean(), 2)),
        pct_vacate_dob_next12m=("label_vacate_or_dobhaz_core", lambda x: round(100 * x.mean(), 2)),
    ).reset_index()
    tier_tbl["avg_units"] = tier_tbl["avg_units"].round(1)
    tier_tbl.to_csv(OUT_REP / "study1_quiet_building_tiers.csv", index=False)

    # Regression battery
    specs = [
        ("quiet_0v_0c", quiet, "label_class_c_any", "z_sister_vc"),
        ("quiet_0v_0c", quiet, "label_serious_any", "z_sister_vc"),
        ("quiet_0v_0c", quiet, "label_vacate_or_dobhaz_core", "z_sister_vc"),
        ("quiet_0v_0c_placebo", quiet, "label_class_c_any", "z_sister_placebo"),
        ("quiet_0v_0c_placebo", quiet, "label_serious_any", "z_sister_placebo"),
        ("quiet_never_sold", quiet[~quiet["_had_sale"]], "label_class_c_any", "z_sister_vc"),
        ("quiet_never_sold", quiet[~quiet["_had_sale"]], "label_serious_any", "z_sister_vc"),
        ("quiet_small_port_le50", quiet[quiet["port_bldgs_log"] <= np.log1p(50)], "label_class_c_any", "z_sister_vc"),
        ("phase4_silent", ann[(ann["silent"] == 1) & (ann["port_sister_vc12_pu"].notna())], "label_class_c_any", "z_sister_vc"),
        ("phase4_silent", ann[(ann["silent"] == 1) & (ann["port_sister_vc12_pu"].notna())], "label_serious_any", "z_sister_vc"),
        ("phase4_silent", ann[(ann["silent"] == 1) & (ann["port_sister_vc12_pu"].notna())], "label_vacate_or_dobhaz_core", "z_sister_vc"),
        ("all_multi_port", ann[ann["port_sister_vc12_pu"].notna()], "label_class_c_any", "z_sister_vc"),
        ("all_multi_port", ann[ann["port_sister_vc12_pu"].notna()], "label_serious_any", "z_sister_vc"),
    ]
    # Also strict HeadOfficer-only portfolio check on quiet buildings
    pfeats_ho = add_asof_portfolio_features(df.loc[ann_mask].reset_index(drop=True), port, max_port_size=200, id_col="ho_portfolio_id")
    ann_ho = ann.copy()
    ann_ho["port_sister_vc12_pu"] = pfeats_ho["port_sister_vc12_pu"].to_numpy()
    ann_ho["_pid"] = pfeats_ho["_pid"].to_numpy()
    ann_ho["port_bldgs_log"] = pfeats_ho["port_bldgs_log"].to_numpy()
    ann_ho["z_sister_vc"] = np.log1p(ann_ho["port_sister_vc12_pu"] * 10.0) / sd_exp
    quiet_ho = ann_ho[(ann_ho["viol_n_12m"] == 0) & (ann_ho["loud_prob_n_12m"] == 0) & (ann_ho["port_sister_vc12_pu"].notna())]
    specs.append(("quiet_headofficer_only", quiet_ho, "label_class_c_any", "z_sister_vc"))
    specs.append(("quiet_headofficer_only", quiet_ho, "label_serious_any", "z_sister_vc"))

    reg_rows = []
    for name, sub, tgt, exp in specs:
        r = run_contagion_logit(sub, tgt, exp)
        reg_rows.append({"slice": name, "outcome": tgt, "exposure": exp, **r})
    reg_df = pd.DataFrame(reg_rows)
    reg_df.to_csv(OUT_REP / "study1_contagion_regressions.csv", index=False)
    con.close()
    return tier_tbl, reg_df


def paired_cluster_bootstrap(y, s_base, s_plus, clusters, metric_fn, n_boot=200, seed=0):
    """Building-clustered paired bootstrap CI for metric(s_plus) - metric(s_base)."""
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(clusters, return_inverse=True)
    n_c = len(uniq)
    # Group row indices by building for fast cluster resampling
    order = np.argsort(inv, kind="mergesort")
    counts = np.bincount(inv, minlength=n_c)
    starts = np.concatenate(([0], np.cumsum(counts[:-1])))

    m_base = metric_fn(y, s_base)
    m_plus = metric_fn(y, s_plus)
    diff = m_plus - m_base

    # Fast approximate paired bootstrap using building-level weights if needed, or direct resampling (subsample up to 200 draws)
    # Exact cluster bootstrap on indices:
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        chosen = rng.integers(0, n_c, size=n_c)
        # Repeat slices
        idx_list = [order[starts[c]:starts[c] + counts[c]] for c in chosen]
        idx = np.concatenate(idx_list)
        diffs[b] = metric_fn(y[idx], s_plus[idx]) - metric_fn(y[idx], s_base[idx])
    lo, hi = np.nanpercentile(diffs, [2.5, 97.5])
    return m_base, m_plus, diff, float(lo), float(hi)


def analysis_1c_walkforward_lift(df: pd.DataFrame, pfeats: pd.DataFrame):
    """Strictly temporal walk-forward LightGBM lift test (all 4 folds, 12m purge gap)."""
    port_cols = [c for c in pfeats.columns if not c.startswith("_")]
    work = pd.concat([df, pfeats[port_cols]], axis=1)

    base_all_cols = [c for c in df.columns if c not in ("bbl", "snapshot_date", "community_district") and not c.startswith("label_")]
    cond_core_cols = [c for c in base_all_cols if CONDITION_SETS["cond_core"](c)]

    folds = make_folds(work["snapshot_date"].unique())
    experiments = [
        ("risk_full_vs_port", "label_serious_any", base_all_cols, base_all_cols + port_cols),
        ("cond_core_vs_port", "label_serious_any", cond_core_cols, cond_core_cols + port_cols),
        ("cond_core_vs_port_vacdob", "label_vacate_or_dobhaz_core", cond_core_cols, cond_core_cols + port_cols),
    ]

    results = []
    for exp_name, target, cols_base, cols_plus in experiments:
        oof_preds = []
        for f in folds:
            tr_in = work.loc[rows(work, f.inner_train)]
            es = work.loc[rows(work, f.es)]
            tr_full = work.loc[rows(work, f.train)]
            ev = work.loc[rows(work, f.eval)]

            b_base, _, _ = fit_lgb(tr_in, es, cols_base, target, seed=10, final_train=tr_full)
            b_plus, _, _ = fit_lgb(tr_in, es, cols_plus, target, seed=10, final_train=tr_full)

            p_base = predict_lgb(b_base, ev, cols_base)
            p_plus = predict_lgb(b_plus, ev, cols_plus)

            ev_out = ev[["bbl", "snapshot_date", "viol_n_12m", "viol_c_n_12m", "viol_open_n",
                         "loud_prob_n_12m", "prior_omo_n", "prior_litig_n", "prior_vacate_n",
                         "prior_aep_n", "static_borough", target]].copy()
            ev_out["fold"] = f.name
            ev_out["p_base"] = p_base
            ev_out["p_plus"] = p_plus
            oof_preds.append(ev_out)

            # Per-fold headline on all + quiet + clean_record
            for sl in ("all", "quiet", "clean_record"):
                m = SLICES[sl](ev_out)
                y = ev_out.loc[m, target].to_numpy()
                sb = ev_out.loc[m, "p_base"].to_numpy()
                sp = ev_out.loc[m, "p_plus"].to_numpy()
                results.append({
                    "experiment": exp_name, "target": target, "fold": f.name, "slice": sl,
                    "n": int(m.sum()), "pos": int(y.sum()),
                    "pr_base": round(average_precision(y, sb), 5),
                    "pr_plus": round(average_precision(y, sp), 5),
                    "pr_diff": round(average_precision(y, sp) - average_precision(y, sb), 5),
                    "roc_base": round(roc_auc(y, sb), 5),
                    "roc_plus": round(roc_auc(y, sp), 5),
                    "roc_diff": round(roc_auc(y, sp) - roc_auc(y, sb), 5),
                    "pr_ci_lo": np.nan, "pr_ci_hi": np.nan, "roc_ci_lo": np.nan, "roc_ci_hi": np.nan,
                })

        # Pooled test fold with building-clustered bootstrap CIs
        test_df = oof_preds[-1]
        for sl in ("all", "quiet", "zero_viol", "clean_record"):
            m = SLICES[sl](test_df)
            y = test_df.loc[m, target].to_numpy()
            sb = test_df.loc[m, "p_base"].to_numpy()
            sp = test_df.loc[m, "p_plus"].to_numpy()
            cl = test_df.loc[m, "bbl"].to_numpy()
            pr_b, pr_p, pr_d, pr_lo, pr_hi = paired_cluster_bootstrap(y, sb, sp, cl, average_precision, n_boot=150, seed=1)
            rc_b, rc_p, rc_d, rc_lo, rc_hi = paired_cluster_bootstrap(y, sb, sp, cl, roc_auc, n_boot=150, seed=2)
            results.append({
                "experiment": exp_name, "target": target, "fold": "test_ci", "slice": sl,
                "n": int(m.sum()), "pos": int(y.sum()),
                "pr_base": round(pr_b, 5), "pr_plus": round(pr_p, 5), "pr_diff": round(pr_d, 5),
                "roc_base": round(rc_b, 5), "roc_plus": round(rc_p, 5), "roc_diff": round(rc_d, 5),
                "pr_ci_lo": round(pr_lo, 5), "pr_ci_hi": round(pr_hi, 5),
                "roc_ci_lo": round(rc_lo, 5), "roc_ci_hi": round(rc_hi, 5),
            })

    res_df = pd.DataFrame(results)
    res_df.to_csv(OUT_REP / "study1_walkforward_lift.csv", index=False)
    return res_df


def main():
    t0 = time.time()
    OUT_REP.mkdir(parents=True, exist_ok=True)
    OUT_PROC.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET threads=6")
    print("[Study 1] Building anonymized portfolio table...", flush=True)
    port = build_portfolio_table(con)
    print(f"  linked {port['portfolio_id'].notna().sum():,} / {len(port):,} lots ({port['portfolio_id'].nunique():,} portfolios) in {time.time()-t0:.1f}s", flush=True)

    print("[Study 1a] Computing registration & portfolio gradients...", flush=True)
    reg_tbl, port_tbl, conc_df = analysis_1a_gradients(con, port)
    con.close()

    print("[Study 1b] Loading panel & computing as-of LOO portfolio features...", flush=True)
    df = load_frame()
    pfeats = add_asof_portfolio_features(df, port, max_port_size=200)
    print(f"  as-of portfolio features ready ({time.time()-t0:.1f}s)", flush=True)

    print("[Study 1b] Running controlled contagion regressions + placebos...", flush=True)
    tier_tbl, reg_df = analysis_1b_contagion(df, port, pfeats)
    print(reg_df[["slice", "outcome", "n", "or", "ci_lo", "ci_hi", "z", "p"]].to_string(index=False), flush=True)

    print("[Study 1c] Running walk-forward LightGBM lift tests (4 folds, purged)...", flush=True)
    wf_df = analysis_1c_walkforward_lift(df, pfeats)
    print(wf_df[wf_df["fold"] == "test_ci"][["experiment", "slice", "pr_base", "pr_plus", "pr_diff", "pr_ci_lo", "pr_ci_hi", "roc_diff", "roc_ci_lo", "roc_ci_hi"]].to_string(index=False), flush=True)

    meta = {
        "study": "Study 1: Landlord Portfolio Networks & Cross-Building Contagion",
        "elapsed_sec": round(time.time() - t0, 1),
        "total_buildings": int(len(port)),
        "linked_buildings": int(port["portfolio_id"].notna().sum()),
        "multi_building_lots_le200": int(((port["port_bldgs"] >= 2) & (port["port_bldgs"] <= 200)).sum()),
    }
    (OUT_REP / "study1_summary.json").write_text(json.dumps(meta, indent=2))
    print(f"[Study 1] Done in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
