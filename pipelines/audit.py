"""Phase 1 data audit: writes docs/data_audit.md from data/raw/*. Run after pull_socrata.py.

Sections: row counts + manifests, key uniqueness, date sanity, BBL quality and join coverage to
PLUTO, inspector no-access rate in HPD complaints (basis of the censoring idea), and text
diversity of violation descriptions (how templated is the text, i.e. is RAG worth it).

Note: the ingest filters (inspectiondate/received_date >= 2018 etc.) remove old and garbage dates
upstream, so "bad date" counts below only measure what survived the filter.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
con = duckdb.connect()
out = ["# Data audit (generated)\n", f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from data/raw/.\n"]

head = []  # headline numbers, inserted at the top of the report at the end

DATASETS = ["hpd_violations", "hpd_complaints", "c311_hpd", "evictions", "hpd_litigations",
            "hpd_omo_charges", "hpd_vacate_orders", "hpd_aep", "hpd_registrations",
            "hpd_reg_contacts", "dob_violations", "pluto"]
# unique key per dataset (column or tuple of columns)
KEYS = {"hpd_violations": ["violationid"], "hpd_complaints": ["problem_id"], "c311_hpd": ["unique_key"],
        "hpd_litigations": ["litigationid"], "hpd_omo_charges": ["omoid"],
        "hpd_vacate_orders": ["building_id", "vacate_order_number"],
        "hpd_registrations": ["registrationid"], "hpd_reg_contacts": ["registrationcontactid"],
        "dob_violations": ["isn_dob_bis_viol"], "pluto": ["bbl"], "hpd_aep": ["building_id", "aep_start_date"]}
# (dataset, date columns, parse) ; DOB dates are 'YYYYMMDD' text, everything else ISO timestamps
DATES = [("hpd_violations", ["inspectiondate", "novissueddate", "currentstatusdate"], "iso"),
         ("hpd_complaints", ["received_date", "complaint_status_date", "problem_status_date"], "iso"),
         ("c311_hpd", ["created_date", "closed_date"], "iso"),
         ("evictions", ["executed_date"], "iso"),
         ("hpd_litigations", ["caseopendate", "findingdate"], "iso"),
         ("hpd_omo_charges", ["omocreatedate", "omoawarddate"], "iso"),
         ("hpd_vacate_orders", ["vacate_effective_date", "actual_rescind_date"], "iso"),
         ("hpd_aep", ["aep_start_date", "discharge_date"], "iso"),
         ("hpd_registrations", ["lastregistrationdate", "registrationenddate"], "iso"),
         ("dob_violations", ["issue_date", "disposition_date"], "ymd")]


def t(name):
    # union_by_name: Socrata omits all-null fields per page, so parts can differ in columns
    return f"read_parquet('{RAW / name}/part-*.parquet', union_by_name=true)"


def have(name):
    return any((RAW / name).glob("part-*.parquet"))


def q(sql):
    return con.sql(sql).fetchall()


def cols(name):
    return [r[0] for r in q(f"describe select * from {t(name)}")]


def section(title, lines):
    out.append(f"\n## {title}\n")
    out.extend(f"- {line}" for line in lines)


def pct(a, b):
    return f"{100 * a / max(b, 1):.2f}%"


# 1. rows and manifests ---------------------------------------------------------------------
lines = []
for n in DATASETS:
    if not have(n):
        lines.append(f"{n}: NOT PULLED")
        continue
    rows = q(f"select count(*) from {t(n)}")[0][0]
    mf = RAW / n / "_manifest.json"
    m = json.loads(mf.read_text()) if mf.exists() else {}
    lines.append(f"{n}: {rows:,} rows, {len(cols(n))} columns, manifest complete={m.get('complete')}, "
                 f"pulled {m.get('pulled_at', '?')[:16]}")
section("Row counts and manifests", lines)

# 2. key uniqueness -------------------------------------------------------------------------
lines = []
for n, key in KEYS.items():
    if have(n):
        k = ", ".join(key)
        rows, distinct = q(f"select count(*), count(distinct ({k})) from {t(n)}")[0] if len(key) > 1 else \
            q(f"select count(*), count(distinct {k}) from {t(n)}")[0]
        lines.append(f"{n} key ({k}): {rows:,} rows, {distinct:,} distinct, duplicates {rows - distinct:,}")
section("Key uniqueness", lines)

# 3. date sanity ----------------------------------------------------------------------------
lines = []
for n, dcols, mode in DATES:
    if not have(n):
        continue
    have_cols = set(cols(n))
    for c in dcols:
        if c not in have_cols:
            lines.append(f"{n}.{c}: column missing")
            continue
        parsed = f"try_cast({c} as timestamp)" if mode == "iso" else f"try_strptime({c}, '%Y%m%d')"
        nn, unp, lo, hi, old, fut = q(f"""
          select count({c}), count({c}) - count({parsed}), min({parsed}), max({parsed}),
                 count(*) filter (where {parsed} < timestamp '2000-01-01'),
                 count(*) filter (where {parsed} > now()) from {t(n)}""")[0]
        lines.append(f"{n}.{c}: non-null {nn:,}; unparseable {unp:,}; range {str(lo)[:10]} to {str(hi)[:10]}; "
                     f"before 2000 {old:,}; in the future {fut:,}")
section("Date sanity (only what survived the ingest filters)", lines)

# 4. BBL quality and join coverage to PLUTO -------------------------------------------------
lines = []
if have("pluto"):
    q(f"create or replace temp view pluto_bbl as select distinct try_cast(bbl as double)::bigint as bbl from {t('pluto')}")
    srcs = {  # name -> SQL selecting a bigint bbl per row
        "hpd_violations (stored bbl)": f"select try_cast(bbl as double)::bigint bbl from {t('hpd_violations')}",
        "hpd_violations (built from boroid/block/lot)": f"""select try_cast(boroid as bigint) * 1000000000
            + try_cast(block as bigint) * 10000 + try_cast(lot as bigint) as bbl from {t('hpd_violations')}""",
        "hpd_complaints (stored bbl)": f"select try_cast(bbl as double)::bigint bbl from {t('hpd_complaints')}",
        "c311_hpd": f"select try_cast(bbl as double)::bigint bbl from {t('c311_hpd')}",
        "evictions": f"select try_cast(bbl as double)::bigint bbl from {t('evictions')}",
        "hpd_litigations": f"select try_cast(bbl as double)::bigint bbl from {t('hpd_litigations')}",
        "hpd_omo_charges": f"select try_cast(bbl as double)::bigint bbl from {t('hpd_omo_charges')}",
        "hpd_vacate_orders": f"select try_cast(bbl as double)::bigint bbl from {t('hpd_vacate_orders')}",
        "hpd_aep": f"select try_cast(bbl as double)::bigint bbl from {t('hpd_aep')}",
        "hpd_registrations (built)": f"""select try_cast(boroid as bigint) * 1000000000
            + try_cast(block as bigint) * 10000 + try_cast(lot as bigint) as bbl from {t('hpd_registrations')}""",
        "dob_violations (built)": f"""select try_cast(boro as bigint) * 1000000000
            + try_cast(block as bigint) * 10000 + try_cast(lot as bigint) as bbl from {t('dob_violations')}"""}
    for label, sql in srcs.items():
        if not have(label.split(" (")[0]):
            continue
        q(f"create or replace temp view s as {sql}")
        rows, nulls, dist, dist_hit, row_hit = q("""
          select count(*), count(*) filter (where s.bbl is null), count(distinct s.bbl),
                 count(distinct s.bbl) filter (where p.bbl is not null),
                 count(*) filter (where p.bbl is not null)
          from s left join pluto_bbl p on s.bbl = p.bbl""")[0]
        unmatched_condo = q("""select count(distinct s.bbl) from s left join pluto_bbl p on s.bbl = p.bbl
          where s.bbl is not null and p.bbl is null and s.bbl % 10000 >= 1001""")[0][0]
        if label == "hpd_violations (stored bbl)":
            head.append(f"BBL join coverage to PLUTO, HPD violations (stored bbl): {pct(dist_hit, dist)} of distinct BBLs, "
                        f"{pct(row_hit, rows)} of rows ({pct(nulls, rows)} of rows have no bbl)")
        lines.append(f"{label}: {rows:,} rows, null/unusable bbl {nulls:,} ({pct(nulls, rows)}); distinct bbl {dist:,}, "
                     f"in PLUTO {dist_hit:,} ({pct(dist_hit, dist)}); rows with a PLUTO match {pct(row_hit, rows)}; "
                     f"unmatched distinct bbl that look like condo unit lots (lot >= 1001): {unmatched_condo:,}")
    if have("hpd_violations"):
        agree, both = q(f"""select count(*) filter (where try_cast(bbl as double)::bigint = try_cast(boroid as bigint) * 1000000000
            + try_cast(block as bigint) * 10000 + try_cast(lot as bigint)), count(*) from {t('hpd_violations')}
            where bbl is not null""")[0]
        lines.append(f"hpd_violations stored bbl equals boroid/block/lot-built bbl in {agree:,} of {both:,} rows ({pct(agree, both)})")
section("BBL quality and join coverage to PLUTO (PLUTO is Bronx/Brooklyn only)", lines)

# 5. inspector no-access (censoring) --------------------------------------------------------
if have("hpd_complaints"):
    c = t("hpd_complaints")
    strict = "status_description ilike '%not able to gain access%'"
    broad = f"({strict} or status_description ilike '%unable to complete the inspection%')"
    n = q(f"select count(*) from {c}")[0][0]
    a = q(f"select count(*) from {c} where {strict}")[0][0]
    b = q(f"select count(*) from {c} where {broad}")[0][0]
    cn = q(f"select count(distinct complaint_id) from {c}")[0][0]
    ca = q(f"select count(distinct complaint_id) from {c} where {strict}")[0][0]
    lines = [f"problem rows {n:,}; distinct complaints {cn:,}",
             f"strict 'not able to gain access' rows: {a:,} ({pct(a, n)}); distinct complaints {ca:,} ({pct(ca, cn)})",
             f"broad (strict + 'unable to complete the inspection'): {b:,} ({pct(b, n)})"]
    by_b = q(f"select borough, count(*), count(*) filter (where {strict}) from {c} group by 1 order by 1")
    lines.append("strict rate by borough: " + "; ".join(f"{r[0]} {pct(r[2], r[1])}" for r in by_b))
    by_y = q(f"""select year(try_cast(received_date as timestamp)) y, count(*), count(*) filter (where {strict})
                 from {c} group by 1 order by 1""")
    lines.append("strict rate by year: " + "; ".join(f"{r[0]} {pct(r[2], r[1])}" for r in by_y))
    head.append(f"HPD complaint inspector no-access: {pct(a, n)} of {n:,} problem rows and {pct(ca, cn)} of {cn:,} "
                f"distinct complaints ({pct(b, n)} of rows with the broader 'unable to complete' wording)")
    head.append("No-access rate by borough: " + "; ".join(f"{r[0]} {pct(r[2], r[1])}" for r in by_b))
    head.append("No-access rate by year: " + "; ".join(f"{r[0]} {pct(r[2], r[1])}" for r in by_y))
    top = q(f"select substr(status_description,1,90), count(*) from {c} group by 1 order by 2 desc limit 6")
    lines.append(f"top status texts: {top}")
    section("HPD complaints: inspector no-access (censoring check)", lines)

# 6. text diversity -------------------------------------------------------------------------
lines = []
for n, col in (("hpd_violations", "novdescription"), ("dob_violations", "description")):
    if not have(n):
        continue
    norm = rf"regexp_replace(regexp_replace(lower(trim({col})), '[0-9]+', '#', 'g'), '\s+', ' ', 'g')"
    rows, raw_d, norm_d = q(f"select count({col}), count(distinct {col}), count(distinct {norm}) from {t(n)}")[0]
    cov = q(f"""with g as (select {norm} s, count(*) c from {t(n)} where {col} is not null group by 1),
                r as (select c, row_number() over (order by c desc) rk from g)
                select sum(c) filter (where rk <= 10), sum(c) filter (where rk <= 100),
                       sum(c) filter (where rk <= 1000), sum(c) from r""")[0]
    head.append(f"{n}.{col}: {pct(norm_d, rows)} of rows distinct after normalizing; top 100 texts cover {pct(cov[1], cov[3])}; "
                f"{pct(q(f'select count(*) from {t(n)} where {col} is null')[0][0], q(f'select count(*) from {t(n)}')[0][0])} null")
    lines.append(f"{n}.{col}: {rows:,} non-null; {raw_d:,} distinct raw ({pct(raw_d, rows)}); "
                 f"{norm_d:,} distinct after lowercasing + digits->'#' ({pct(norm_d, rows)}); "
                 f"top 10 / 100 / 1000 normalized texts cover {pct(cov[0], cov[3])} / {pct(cov[1], cov[3])} / {pct(cov[2], cov[3])} of rows")
section("Text diversity (how templated are violation descriptions)", lines)

out[2:2] = ["\n## Headline numbers\n", *[f"- {h}" for h in head]]
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "data_audit.md").write_text("\n".join(out) + "\n")
print("wrote docs/data_audit.md")
