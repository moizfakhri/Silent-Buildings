"""Phase 1 dataset registry: what to pull, how to filter it (Brooklyn + Bronx, 2018 onward).

Filters are SoQL $where clauses. Borough codes differ per dataset (verified 2026-11-13 from samples):
HPD violations/litigations use boroid '2'=Bronx '3'=Brooklyn; HPD complaints use borough names;
DOB violations use boro '2'/'3'; PLUTO uses 'BX'/'BK'.
"""

SINCE = "2018-01-01"

DATASETS = {
    "hpd_violations": dict(id="wvxf-dwi5", where=f"boroid in ('2','3') AND inspectiondate >= '{SINCE}' AND inspectiondate < '2027-01-01'"),
    "hpd_complaints": dict(id="ygpa-z7cr", where=f"borough in ('BRONX','BROOKLYN') AND received_date >= '{SINCE}'"),
    "c311_hpd": dict(id="erm2-nwe9", where=f"agency='HPD' AND borough in ('BRONX','BROOKLYN') AND created_date >= '{SINCE}'"),
    "evictions": dict(id="6z8x-wfk4", where=f"borough in ('BRONX','BROOKLYN') AND executed_date >= '{SINCE}'"),
    "hpd_litigations": dict(id="59kj-x8nc", where=f"boroid in ('2','3') AND caseopendate >= '{SINCE}'"),
    "hpd_omo_charges": dict(id="mdbu-nrqn", where=None),
    "hpd_vacate_orders": dict(id="tb8q-a3ar", where=None),
    "hpd_aep": dict(id="hcir-3275", where=None),
    "hpd_registrations": dict(id="tesw-yqqr", where="boroid in ('2','3')"),
    "hpd_reg_contacts": dict(id="feu5-w2e2", where=None),
    "dob_violations": dict(id="3h2n-5cm9", where="boro in ('2','3') AND issue_date >= '20180101'"),
    "pluto": dict(id="64uk-42ks", where="borough in ('BX','BK')"),
    # Phase 5 (sales): DOF annualized calendar sales, complete for 2016-2025 (the ACRIS Master open-data extract covers only about 8% of recent deed volume).
    "dof_sales": dict(id="w2pb-icbu", where="borough in ('2','3') AND sale_date >= '2016-01-01'"),
    # Phase 6 (map): building footprints with roof height and geometry (WGS84 MultiPolygon as JSON text). 434,383 rows for BX+BK.
    "building_footprints": dict(id="5zhs-2jue", where="base_bbl like '2%' OR base_bbl like '3%'"),
}
