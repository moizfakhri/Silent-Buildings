"""Phase 2 tests, all on the synthetic fixture (no real data needed):
  (a) as-of invariance: features at t do not change when everything after t is removed or
      perturbed, (b) label windows do not overlap feature windows, (c) no duplicate keys,
  (d) the SQL agrees with a brute-force pandas oracle on every (bbl, snapshot), plus
  hand-checked edge cases and the staging cleaning rules.
"""
from datetime import date
from types import SimpleNamespace

import fixture_data as fx
import pandas as pd
import pytest
from oracle import compare, oracle

from nycdistress.build import build, check_params

PARAMS = dict(first_snapshot="2019-01-01", last_snapshot="2022-01-01")  # 13 quarterly snapshots
LABELS = ["label_vacate", "label_aep", "label_vacate_or_aep", "label_omo", "label_litigation", "label_serious_any",
          "label_loud_complaints_next12"]


def run_build(tmp, frames, params=PARAMS, name="run"):
    raw = tmp / f"{name}_raw"
    fx.write_raw(frames, raw)
    out = tmp / f"{name}_out"
    con = build(raw_dir=raw, out_dir=out, tmp_dir=tmp / "duck", params=params, verbose=False)
    def load(name):
        df = pd.read_parquet(out / f"{name}.parquet")
        if "snapshot_date" in df:   # DuckDB DATE comes back as python date objects
            df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
        return df

    return SimpleNamespace(con=con, out=out, features=load("features"), labels=load("labels"), spine=load("spine"))


@pytest.fixture(scope="module")
def frames():
    return fx.make_frames()


@pytest.fixture(scope="module")
def built(tmp_path_factory, frames):
    return run_build(tmp_path_factory.mktemp("full"), frames)


# ---------------------------------------------------------------------------------- (c) keys
def test_no_duplicate_keys_and_matching_tables(built):
    f, lab = built.features, built.labels
    assert not f.duplicated(["bbl", "snapshot_date"]).any()
    assert not lab.duplicated(["bbl", "snapshot_date"]).any()
    assert len(f) == len(lab)
    assert set(zip(f.bbl, f.snapshot_date)) == set(zip(lab.bbl, lab.snapshot_date))
    assert f.bbl.str.fullmatch(r"\d{10}").all() and built.spine.bbl.str.fullmatch(r"\d{10}").all()
    assert not built.spine.duplicated("bbl").any()


def test_spine_rules(built, frames):
    sp = built.spine
    excluded = {frames["pluto"].bbl.iloc[3][:10], frames["pluto"].bbl.iloc[4][:10]}  # 2 units; landuse 06
    assert not excluded & set(sp.bbl)
    late = frames["pluto"].bbl.iloc[5][:10]  # yearbuilt 2021: only exists from the 2022-01-01 snapshot on
    snaps = built.features[built.features.bbl == late].snapshot_date
    assert snaps.min() == pd.Timestamp("2022-01-01") and len(snaps) == 1
    unknown = frames["pluto"].bbl.iloc[6][:10]  # yearbuilt 0 = unknown: kept at every snapshot
    assert len(built.features[built.features.bbl == unknown]) == 13
    assert (built.spine.unitsres >= 3).all() and set(built.spine.borough) <= {"BX", "BK"}
    assert built.spine.community_district.notna().all() and built.spine.census_tract_2010.notna().all()


# ---------------------------------------------------------------------------------- (d) oracle
def test_sql_matches_bruteforce_oracle_everywhere(built, frames):
    rows = built.features.merge(built.labels, on=["bbl", "snapshot_date"]).set_index(["bbl", "snapshot_date"])
    bad, n = [], 0
    for (bbl, snap), row in rows.iterrows():
        exp = oracle(frames, int(bbl), snap.date())
        mism = compare(exp, row)
        n += 1
        if mism:
            bad.append((bbl, snap.date(), mism[:3]))
    assert n == len(rows) > 400
    assert not bad, f"{len(bad)} of {n} rows differ from the oracle, e.g. {bad[:3]}"


def test_static_columns_match_spine(built):
    m = built.features.merge(built.spine, on="bbl")
    assert (m.static_unitsres == m.unitsres).all() and (m.static_bldgclass == m.bldgclass).all()
    known = m.yearbuilt.notna()
    assert (m.static_age_at_t[known] == m.snapshot_date.dt.year[known] - m.yearbuilt[known]).all()
    assert m.static_age_at_t[~known].isna().all()


# ---------------------------------------------------------------------------------- (b) windows
def test_label_window_is_the_next_feature_window(built):
    """Structural proof that feature windows end at t and label windows start right after t:
    an event is in label(t) iff it is counted by the cumulative/12m feature at t+12m but not at t."""
    f = built.features.merge(built.labels, on=["bbl", "snapshot_date"])
    f["later"] = f.snapshot_date + pd.DateOffset(years=1)
    j = f.merge(f, left_on=["bbl", "later"], right_on=["bbl", "snapshot_date"], suffixes=("", "_next"))
    assert len(j) > 300
    for lab, cum in (("label_omo", "prior_omo_n"), ("label_litigation", "prior_litig_n"),
                     ("label_vacate", "prior_vacate_n"), ("label_aep", "prior_aep_n")):
        assert (j[lab] == (j[cum + "_next"] > j[cum]).astype(int)).all(), lab
    # complaint problems received in (t, t+12m] == the 12-month window feature measured at t+12m
    assert (j.label_loud_complaints_next12 == j.loud_prob_n_12m_next).all()
    assert (j.label_loud_complaints_next12 > 0).any()
    assert (j.label_serious_any == j[["label_vacate", "label_aep", "label_omo", "label_litigation"]].max(axis=1)).all()
    assert (j.label_vacate_or_aep == j[["label_vacate", "label_aep"]].max(axis=1)).all()
    assert (j.label_vacate_or_dobhaz == j[["label_vacate", "label_dob_hazard"]].max(axis=1)).all()
    assert (j.label_vacate_or_dobhaz_core == j[["label_vacate", "label_dob_hazard_core"]].max(axis=1)).all()
    assert (j.label_dob_hazard_core <= j.label_dob_hazard).all()          # the core definition is a subset of the wide one
    assert j.label_dob_hazard.sum() > 0 and j.label_dob_hazard_core.sum() > 0


def test_hand_checked_edge_cases(tmp_path):
    """Only the hand-placed rows for one lot, expected values worked out by hand."""
    b = run_build(tmp_path, fx.make_edge_frames(), params=dict(first_snapshot="2019-10-01", last_snapshot="2021-04-01"), name="edge")
    r = b.features.merge(b.labels, on=["bbl", "snapshot_date"]).set_index("snapshot_date")
    t = lambda s: r.loc[pd.Timestamp(s)]  # noqa: E731
    # OMO events: 2020-01-01, 2020-01-02, 2021-01-01, 2021-01-02. An event ON t is a feature, never a label.
    assert (t("2019-10-01").prior_omo_n, t("2019-10-01").label_omo) == (0, 1)
    assert (t("2020-01-01").prior_omo_n, t("2020-01-01").prior_omo_n_12m, t("2020-01-01").label_omo) == (1, 1, 1)
    assert t("2020-01-01").prior_omo_months_since == 0
    assert (t("2021-01-01").prior_omo_n, t("2021-01-01").label_omo) == (3, 1)   # 2021-01-02 is inside (t, t+12m]
    assert t("2021-04-01").prior_omo_n == 4
    # violations (class A) on 2019-01-01, 2019-01-02, 2020-01-01, 2020-01-02; 12m window at 2020-01-01 is (2019-01-01, 2020-01-01]
    assert t("2020-01-01").viol_a_n_12m == 2 and t("2020-01-01").viol_a_n_3m == 1
    assert pd.isna(t("2020-01-01").viol_a_n_36m)            # window starts before the 2018 extract: unknown, not 0
    assert t("2020-01-01").viol_open_a_n == 0                # all closed on 2020-01-01 <= t
    assert t("2019-10-01").viol_open_a_n == 2                # 2 inspected by t, both close on 2020-01-01 > t: still open at t
    # complaints received 2019-01-01, 01-02, 2020-01-01, 01-02, 2021-01-01, 01-02 (each closed the next day)
    assert t("2020-01-01").loud_prob_n_12m == 2              # 2019-01-02 and 2020-01-01 (2019-01-01 is exactly t-12m: excluded)
    assert t("2020-01-01").label_loud_complaints_next12 == 2  # 2020-01-02 and 2021-01-01 (t+12m is included; 2021-01-02 is not)
    # a no-access outcome is only known on the closure date (the day after receipt here): the complaints
    # received 2019-01-01 and 2019-01-02 are closed by t, the one received ON t closes 2020-01-02 and must not count yet
    assert t("2020-01-01").loud_closed_n_12m == 2 and t("2020-01-01").loud_nacc_n_12m == 2
    assert t("2020-01-01").loud_open_prob_n == 1             # received <= t (3) minus known closed by t (2)
    assert pd.isna(t("2020-01-01").loud_311_n_12m)           # 311 extract starts 2020-01-01: 12m window not covered


# ---------------------------------------------------------------------------------- (a) as-of invariance
def _event_date(name, df):
    col = dict(hpd_violations="inspectiondate", hpd_complaints="received_date", c311_hpd="created_date",
               evictions="executed_date", hpd_litigations="caseopendate", hpd_vacate_orders="vacate_effective_date",
               hpd_aep="aep_start_date", hpd_omo_charges="omocreatedate", dob_violations="issue_date")[name]
    if name == "dob_violations":
        return pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")
    return pd.to_datetime(df[col], errors="coerce")


FAR = "2099-01-01T00:00:00.000"


def truncate_and_perturb(frames, t):
    """Remove every event dated after t, and scramble information that only exists after t."""
    t = pd.Timestamp(t)
    out, changed = {}, 0
    for name, df in frames.items():
        if name in ("pluto", "hpd_registrations", "hpd_reg_contacts"):
            out[name] = df
            continue
        d = _event_date(name, df)
        keep = ~(d > t)
        df = df[keep].copy()
        changed += int((~keep).sum())
        if name == "hpd_violations":   # closure dates after t: push far away (still not closed at t)
            late = pd.to_datetime(df.currentstatusdate, errors="coerce") > t
            df.loc[late, "currentstatusdate"] = FAR
            changed += int(late.sum())
        if name == "hpd_complaints":   # outcomes known only after t: rewrite them
            late = (pd.to_datetime(df.complaint_status_date, errors="coerce") > t) | (pd.to_datetime(df.problem_status_date, errors="coerce") > t)
            df.loc[late, ["complaint_status_date", "problem_status_date"]] = FAR
            df.loc[late, "status_description"] = "The Department of Housing Preservation and Development was not able to gain access to inspect the following conditions."
            changed += int(late.sum())
        if name == "hpd_vacate_orders":
            late = pd.to_datetime(df.actual_rescind_date, errors="coerce") > t
            df.loc[late, "actual_rescind_date"] = None
            changed += int(late.sum())
        if name == "hpd_aep":
            late = pd.to_datetime(df.discharge_date, errors="coerce") > t
            df.loc[late, "discharge_date"] = None
            changed += int(late.sum())
        out[name] = df
    assert changed > 100, "truncation/perturbation did nothing: the test would be vacuous"
    return out


@pytest.mark.parametrize("t", ["2019-07-01", "2020-01-01", "2021-04-01"])
def test_features_at_t_ignore_everything_after_t(tmp_path, built, frames, t):
    mini = run_build(tmp_path, truncate_and_perturb(frames, t), params=dict(first_snapshot=t, last_snapshot=t), name="trunc")
    full = built.features[built.features.snapshot_date == pd.Timestamp(t)].sort_values("bbl").reset_index(drop=True)
    cut = mini.features.sort_values("bbl").reset_index(drop=True)
    assert len(full) == len(cut) > 30
    pd.testing.assert_frame_equal(full, cut, check_dtype=False)


# ---------------------------------------------------------------------------------- staging rules
def test_staging_cleaning_rules(built, frames):
    q = lambda s: built.con.execute(s).fetchall()  # noqa: E731
    assert q("select count(*) from stg_aep")[0][0] == 12                       # exact duplicate row collapsed
    assert q("select count(*) from stg_vacate where d_vacate > DATE '2026-11-14'")[0][0] == 0   # 2040 row dropped
    assert q("select count(*) from stg_litigations where litigationid in ('e1','e2')")[0][0] == 0  # 2030 date, null bbl
    assert q("select count(*) from stg_dob where isn_dob_bis_viol = 'bad'")[0][0] == 0           # unparseable date
    assert q("select count(*) from stg_violations where bbl is null")[0][0] == 0
    assert q("select count(*) from stg_violations")[0][0] == len(frames["hpd_violations"])  # null stored bbl rebuilt from block/lot
    assert q("select count(*) from stg_complaints")[0][0] == len(frames["hpd_complaints"])
    assert q("select count(*) from stg_pluto where bbl = 3000010001")[0][0] == 1       # '3000010001.00000000' normalised
    reg = q("select d_last_reg from stg_registrations")
    assert len(reg) == 1 and reg[0][0] == date(2025, 1, 1)                            # newest registration kept
    cont = q("select registrationcontactid, corporationname from stg_reg_contacts order by 1")
    assert cont == [("1", "ACME LLC"), ("2", None)]                                   # most complete duplicate kept
    assert q("select count(*) from stg_complaints where d_closed_known < d_recv")[0][0] == 0   # closure never before receipt
    assert q("select count(*) from stg_evictions")[0][0] == (frames["evictions"].residential_commercial_ind == "Residential").sum()


def test_snapshot_grid_validation():
    check_params(dict(grid_base="2018-01-01", first_snapshot="2019-01-01", last_snapshot="2025-10-01"))
    for bad in (dict(first_snapshot="2019-02-01"), dict(first_snapshot="2019-01-15"), dict(last_snapshot="2018-10-01")):
        with pytest.raises(ValueError):
            check_params({**dict(grid_base="2018-01-01", first_snapshot="2019-01-01", last_snapshot="2025-10-01"), **bad})
