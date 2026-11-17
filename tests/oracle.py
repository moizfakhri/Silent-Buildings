"""Brute-force reference implementation of the Phase 2 features and labels for ONE building at ONE
snapshot, using plain pandas and exact date arithmetic (no quarter buckets). It reads raw-shaped
string DataFrames. Used to check the SQL pipeline on a synthetic fixture and on real buildings.

Window convention: a w-month feature window is (t - w months, t]; a label window is (t, t + 12 months].
"""
from datetime import date

import pandas as pd

CUTOFF = date(2026, 11, 14)
SRC_START = date(2018, 1, 1)
C311_START = date(2020, 1, 1)


def _d(x):
    return pd.to_datetime(x, errors="coerce").date() if pd.notna(pd.to_datetime(x, errors="coerce")) else None


def _norm_bbl(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _build_bbl(boro, block, lot):
    try:
        return int(boro) * 1_000_000_000 + int(block) * 10_000 + int(lot)
    except (TypeError, ValueError):
        return None


def _gmax(*xs):
    """max over non-None values (SQL GREATEST ignores NULLs); None if all are None."""
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else None


def _keep(df, mask):
    """Rows where mask is true. Safe for empty frames (df[[]] would select zero COLUMNS)."""
    return df.loc[pd.Series(list(mask), index=df.index, dtype=bool)]


def add_months(d, m):
    y, mo = divmod(d.year * 12 + d.month - 1 + m, 12)
    return date(y, mo + 1, 1).replace(day=min(d.day, 28)) if d.day > 28 else date(y, mo + 1, d.day)


def month_diff(a, b):
    """Calendar-month difference like DuckDB datediff('month', a, b)."""
    return (b.year - a.year) * 12 + b.month - a.month


def win(dates, t, w):
    """Count of dates in (t - w months, t]."""
    lo = add_months(t, -w)
    return sum(1 for d in dates if d is not None and lo < d <= t)


def fwin(dates, t, w=12):
    hi = add_months(t, w)
    return sum(1 for d in dates if d is not None and t < d <= hi)


def complete(t, w, start):
    return add_months(t, -w) >= start


def _wcols(out, name, dates, t, windows, start):
    for w, tag in windows:
        out[f"{name}_{tag}"] = win(dates, t, w) if complete(t, w, start) else None


def bbl_rows(df, bbl, kind):
    """Rows of a raw DataFrame belonging to `bbl`, with the same BBL rules as staging."""
    if kind == "viol":
        keys = [(_norm_bbl(b) if _norm_bbl(b) is not None else _build_bbl(bo, bl, lt))
                for b, bo, bl, lt in zip(df.bbl, df.boroid, df.block, df.lot)]
    elif kind == "cmp":
        bm = {"BRONX": 2, "BROOKLYN": 3}
        keys = [(_norm_bbl(b) if _norm_bbl(b) is not None else _build_bbl(bm.get(bo), bl, lt))
                for b, bo, bl, lt in zip(df.bbl, df.borough, df.block, df.lot)]
    elif kind == "omo":
        keys = [(_norm_bbl(b) if _norm_bbl(b) is not None else _build_bbl(bo, bl, lt))
                for b, bo, bl, lt in zip(df.bbl, df.boro_id, df.block, df.lot)]
    elif kind == "dob":
        keys = [_build_bbl(bo, bl, lt) for bo, bl, lt in zip(df.boro, df.block, df.lot)]
    else:
        keys = [_norm_bbl(b) for b in df.bbl]
    return _keep(df, [k == bbl for k in keys])


def oracle(raw, bbl, t):
    """raw: dict name -> raw-shaped DataFrame (already filtered to anything; filtered again here)."""
    out = {}
    W = [(3, "3m"), (12, "12m"), (36, "36m")]

    # ---------------- HPD violations
    v = bbl_rows(raw["hpd_violations"], bbl, "viol")
    v = v.assign(d=[_d(x) for x in v.inspectiondate])
    v = _keep(v, [d is not None and d <= CUTOFF for d in v.d])
    v["closed"] = v.violationstatus == "Close"
    v["dc"] = [_gmax(_d(cs), d) if c else None for cs, d, c in zip(v.currentstatusdate, v.d, v.closed)]
    for cls, tag in ((None, ""), ("A", "a_"), ("B", "b_"), ("C", "c_")):
        sub = v if cls is None else v[v["class"] == cls]
        _wcols(out, f"viol_{tag}n", list(sub.d), t, W, SRC_START)
        opn = sum(1 for d, c, dc in zip(sub.d, sub.closed, sub.dc) if d <= t and not (c and dc is not None and dc <= t))
        out["viol_open_n" if cls is None else f"viol_open_{tag}n"] = opn

    # ---------------- HPD complaints
    c = bbl_rows(raw["hpd_complaints"], bbl, "cmp")
    c = c.assign(d=[_d(x) for x in c.received_date])
    c = _keep(c, [d is not None and d <= CUTOFF for d in c.d])
    both = (c.complaint_status == "CLOSE") & (c.problem_status == "CLOSE")
    c["dk"] = [_gmax(_d(cs), _d(ps), d) if b else None for cs, ps, d, b in
               zip(c.complaint_status_date, c.problem_status_date, c.d, both)]
    c["emerg"] = c.type.isin(["EMERGENCY", "IMMEDIATE EMERGENCY"])
    c["nacc"] = c.status_description.fillna("").str.contains("not able to gain access", case=False)
    cats = {"heat_hot_water": "HEAT/HOT WATER", "unsanitary": "UNSANITARY CONDITION", "plumbing": "PLUMBING",
            "paint_plaster": "PAINT/PLASTER", "door_window": "DOOR/WINDOW", "water_leak": "WATER LEAK",
            "electric": "ELECTRIC"}
    c["cat"] = [next((k for k, v_ in cats.items() if v_ == m), "other") for m in c.major_category]
    _wcols(out, "loud_prob_n", list(c.d), t, W, SRC_START)
    for w, tag in W:
        lo = add_months(t, -w)
        sel = _keep(c, [lo < d <= t for d in c.d])
        out[f"loud_cmpl_n_{tag}"] = sel.complaint_id.nunique() if complete(t, w, SRC_START) else None
    _wcols(out, "loud_emerg_n", list(c[c.emerg].d), t, W, SRC_START)
    _wcols(out, "loud_nonemerg_n", list(c[~c.emerg].d), t, W, SRC_START)
    _wcols(out, "loud_heat_n", list(c[c.cat == "heat_hot_water"].d), t, W, SRC_START)
    for cat in ("unsanitary", "plumbing", "paint_plaster", "door_window", "water_leak", "electric", "other"):
        _wcols(out, f"loud_cat_{cat}_n", list(c[c.cat == cat].d), t, [(12, "12m")], SRC_START)
    out["loud_open_prob_n"] = sum(1 for d in c.d if d <= t) - sum(1 for d in c.dk if d is not None and d <= t)
    _wcols(out, "loud_closed_n", list(c.dk), t, W, SRC_START)
    _wcols(out, "loud_nacc_n", list(c[c.nacc].dk), t, W, SRC_START)
    for w, tag in W[1:]:
        cl, na = out[f"loud_closed_n_{tag}"], out[f"loud_nacc_n_{tag}"]
        out[f"loud_nacc_share_{tag}"] = (na / cl) if cl else None

    # ---------------- 311
    k = bbl_rows(raw["c311_hpd"], bbl, "other")
    k = k.assign(d=[_d(x) for x in k.created_date])
    k = _keep(k, [d is not None and d <= CUTOFF for d in k.d])
    _wcols(out, "loud_311_n", list(k.d), t, W, C311_START)
    _wcols(out, "loud_311_heat_n", list(k[k.complaint_type == "HEAT/HOT WATER"].d), t, [(12, "12m")], C311_START)

    # ---------------- evictions
    e = bbl_rows(raw["evictions"], bbl, "other")
    e = e[e.residential_commercial_ind == "Residential"]
    ed = [x for x in (_d(v_) for v_ in e.executed_date) if x is not None and x <= CUTOFF]
    _wcols(out, "evict_n", ed, t, W[1:], SRC_START)

    # ---------------- DOB
    b = bbl_rows(raw["dob_violations"], bbl, "dob")
    b = b.assign(d=[pd.to_datetime(x, format="%Y%m%d", errors="coerce") for x in b.issue_date])
    b = _keep(b, [pd.notna(x) for x in b.d])
    b = b.assign(d=[x.date() for x in b.d])
    b = _keep(b, [d <= CUTOFF for d in b.d])
    vt = b.violation_type.fillna("")
    grp = ["elevator" if "ELEVATOR" in x.upper() else "boiler" if "BOILER" in x.upper()
           else "construction" if x.upper().startswith("C-CONSTRUCTION") else "other" for x in vt]
    b["grp"] = grp
    _wcols(out, "dob_n", list(b.d), t, W[1:], SRC_START)
    for g in ("elevator", "boiler", "construction"):
        _wcols(out, f"dob_{g}_n", list(b[b.grp == g].d), t, [(12, "12m")], SRC_START)

    # ---------------- prior events and labels
    li = bbl_rows(raw["hpd_litigations"], bbl, "other")
    ld = [x for x in (_d(v_) for v_ in li.caseopendate) if x is not None and x <= CUTOFF]
    om = bbl_rows(raw["hpd_omo_charges"], bbl, "omo")
    od = [x for x in (_d(v_) for v_ in om.omocreatedate) if x is not None and x <= CUTOFF]
    va = bbl_rows(raw["hpd_vacate_orders"], bbl, "other")
    vrows = [(_d(a), _d(r)) for a, r in zip(va.vacate_effective_date, va.actual_rescind_date)]
    vrows = [(a, r) for a, r in vrows if a is not None and a <= CUTOFF]
    ae = bbl_rows(raw["hpd_aep"], bbl, "other")
    ae = ae.assign(s=[_d(x) for x in ae.aep_start_date], dd=[_d(x) for x in ae.discharge_date])
    ae = _keep(ae, [s_ is not None for s_ in ae.s])
    ae["nd"] = [d is None for d in ae.dd]
    ae = ae.sort_values(["building_id", "s", "nd", "dd"], ascending=[True, True, True, False]).drop_duplicates(["building_id", "s"])
    arows = list(zip(ae.s, ae.dd))

    def prior(dates):
        past = [d for d in dates if d <= t]
        return len(past), (month_diff(max(past), t) if past else None)

    out["prior_litig_n"], out["prior_litig_months_since"] = prior(ld)
    out["prior_litig_n_12m"] = win(ld, t, 12) if complete(t, 12, SRC_START) else None
    out["prior_omo_n"], out["prior_omo_months_since"] = prior(od)
    out["prior_omo_n_12m"] = win(od, t, 12) if complete(t, 12, SRC_START) else None
    for name, rows in (("vacate", vrows), ("aep", arows)):
        n, ms = prior([a for a, _ in rows])
        out[f"prior_{name}_n"], out[f"prior_{name}_months_since"] = n, ms
        out[f"prior_{name}_active_n"] = sum(1 for a, r in rows if a <= t and not (r is not None and r >= a and r <= t))

    out["label_vacate"] = int(fwin([a for a, _ in vrows], t) > 0)
    out["label_aep"] = int(fwin([a for a, _ in arows], t) > 0)
    out["label_omo"] = int(fwin(od, t) > 0)
    out["label_litigation"] = int(fwin(ld, t) > 0)
    bt = b.assign(code=[str(x).split("-")[0] for x in b.violation_type]) if len(b) else b.assign(code=[])
    haz_core = list(bt[bt.code.isin(["IMEGNCY", "UB", "FISPHAZ", "EGNCY"])].d)
    haz = list(bt[bt.code.isin(["IMEGNCY", "UB", "FISPHAZ", "EGNCY", "AEUHAZ1"])].d)
    out["label_dob_hazard"] = int(fwin(haz, t) > 0)
    out["label_dob_hazard_core"] = int(fwin(haz_core, t) > 0)
    out["label_vacate_or_dobhaz"] = int(out["label_vacate"] or out["label_dob_hazard"])
    out["label_vacate_or_dobhaz_core"] = int(out["label_vacate"] or out["label_dob_hazard_core"])
    out["label_vacate_or_aep"] = int(out["label_vacate"] or out["label_aep"])
    out["label_serious_any"] = int(any(out[k_] for k_ in ("label_vacate", "label_aep", "label_omo", "label_litigation")))
    out["label_loud_complaints_next12"] = fwin(list(c.d), t)
    return out


def compare(expected, actual_row, tol=1e-6):
    """Return a list of (column, expected, actual) mismatches. NaN/None are equal."""
    bad = []
    for col, ev in expected.items():
        av = actual_row[col]
        av = None if pd.isna(av) else av
        if ev is None or av is None:
            if ev is not av and not (ev is None and av is None):
                bad.append((col, ev, av))
        elif abs(float(ev) - float(av)) > tol:
            bad.append((col, ev, av))
    return bad
