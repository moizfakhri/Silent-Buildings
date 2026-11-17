"""Sale cohorts for the after-the-sale study: whole-building arms-length sales of analysis buildings, from DOF annualized sales.

A "sale" is a DOF row on the building's BBL, with no apartment number, in a whole-building category (three-family, rental walk-up, rental
elevator, 4-10 unit rental), priced at least $100,000 and at least $25,000 per residential unit (a proxy for arms-length: nominal and intra-family
transfers are cheap). Condo units, parking and co-op apartments are apartment-level transactions recorded on the building lot and are excluded.
A building's treatment quarter is the calendar quarter of its FIRST such sale (quarter 0 = 2018Q1); buildings with a second sale inside the event window are dropped.
"""
import duckdb

WHOLE_BUILDING = ("03 THREE FAMILY DWELLINGS", "07 RENTALS - WALKUP APARTMENTS", "08 RENTALS - ELEVATOR APARTMENTS", "14 RENTALS - 4-10 UNIT")
MIN_PRICE = 100_000
MIN_PRICE_PER_UNIT = 25_000


def quarter_index(year, month):
    return (year - 2018) * 4 + (month - 1) // 3


def build_cohorts(dof_glob, spine_path, pre=8, post=8, last_q=34, first_year=2018):
    """Returns (cohort rows [(bbl, q0)], never-sold bbls, steps [(description, count)]).

    `never-sold` = analysis buildings with NO DOF row at all in the whole-building categories in the data, priced or not (so nominal transfers do not contaminate controls).
    """
    con = duckdb.connect()
    con.execute(f"""CREATE TABLE sales AS
        SELECT lpad(CAST(TRY_CAST(bbl AS BIGINT) AS VARCHAR), 10, '0') AS bbl, CAST(TRY_CAST(sale_date AS TIMESTAMP) AS DATE) AS sale_date,
               TRY_CAST(sale_price AS DOUBLE) AS price, building_class_category AS category, nullif(trim(apartment_number), '') AS apt
        FROM read_parquet('{dof_glob}', union_by_name=true) WHERE TRY_CAST(bbl AS BIGINT) IS NOT NULL""")
    con.execute(f"CREATE TABLE spine AS SELECT bbl, unitsres AS units FROM read_parquet('{spine_path}')")
    steps = [("DOF sale rows in the data", con.execute("SELECT count(*) FROM sales").fetchone()[0])]
    cats = ", ".join(f"'{c}'" for c in WHOLE_BUILDING)
    con.execute(f"CREATE TABLE whole AS SELECT s.*, p.units FROM sales s JOIN spine p USING (bbl) WHERE s.apt IS NULL AND s.category IN ({cats})")
    steps.append(("whole-building rows on analysis buildings (any price, any year)", con.execute("SELECT count(*) FROM whole").fetchone()[0]))
    con.execute(f"""CREATE TABLE arms AS
        SELECT bbl, sale_date, (year(sale_date) - 2018) * 4 + (month(sale_date) - 1) // 3 AS qs FROM whole
        WHERE sale_date >= DATE '{first_year}-01-01' AND price >= {MIN_PRICE} AND price >= {MIN_PRICE_PER_UNIT} * units""")
    steps.append(("arms-length proxy sales 2018 onward", con.execute("SELECT count(*) FROM arms").fetchone()[0]))
    con.execute("CREATE TABLE firsts AS SELECT bbl, min(qs) AS q0 FROM arms GROUP BY bbl")
    steps.append(("distinct buildings with such a sale", con.execute("SELECT count(*) FROM firsts").fetchone()[0]))
    con.execute(f"""CREATE TABLE cohort AS SELECT f.bbl, f.q0 FROM firsts f
        WHERE f.q0 BETWEEN {pre} AND {last_q - post}
          AND NOT EXISTS (SELECT 1 FROM arms a WHERE a.bbl = f.bbl AND a.qs <> f.q0 AND a.qs BETWEEN f.q0 - {pre} AND f.q0 + {post})""")
    steps.append((f"first sale with a full window ({pre} before, {post} after) and no other sale inside it", con.execute("SELECT count(*) FROM cohort").fetchone()[0]))
    cohort = con.execute("SELECT bbl, q0 FROM cohort ORDER BY bbl").fetchall()
    never = [r[0] for r in con.execute("SELECT bbl FROM spine WHERE bbl NOT IN (SELECT bbl FROM whole) ORDER BY bbl").fetchall()]
    steps.append(("analysis buildings with no whole-building DOF row at all (never-treated controls)", len(never)))
    return cohort, never, steps
