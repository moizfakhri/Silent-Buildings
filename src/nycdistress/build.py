"""Phase 2 builder: runs pipelines/sql/*.sql through DuckDB and writes data/processed/*.parquet.

SQL files are executed in filename order after `{{name}}` placeholders are substituted from the
parameters below. Raw Parquet (all strings) is exposed to SQL as views named raw_<dataset>.

    python pipelines/build_features.py            # full data
    make features
"""
import json
import time
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "pipelines" / "sql"
RAW_NAMES = ["hpd_violations", "hpd_complaints", "c311_hpd", "evictions", "hpd_litigations",
             "hpd_omo_charges", "hpd_vacate_orders", "hpd_aep", "hpd_registrations",
             "hpd_reg_contacts", "dob_violations", "pluto"]
DEFAULTS = dict(
    grid_base="2018-01-01",       # quarter 0 of the bucket grid; also the start of most sources
    first_snapshot="2019-01-01",
    last_snapshot="2025-10-01",   # last quarter whose 12-month label window is inside the data
    data_cutoff="2026-11-14",     # pull date: source dates after this are treated as bad
    c311_start="2020-01-01",      # first date covered by the 311 extract
)
OUTPUTS = ["spine", "features", "labels"]


def check_params(p):
    base, first, last = (date.fromisoformat(p[k]) for k in ("grid_base", "first_snapshot", "last_snapshot"))
    for name, d in (("grid_base", base), ("first_snapshot", first), ("last_snapshot", last)):
        if d.day != 1:
            raise ValueError(f"{name} must be the 1st of a month, got {d}")
    for name, d in (("first_snapshot", first), ("last_snapshot", last)):
        if ((d.year - base.year) * 12 + d.month - base.month) % 3:
            raise ValueError(f"{name} {d} is not on the quarterly grid anchored at {base}")
    if last < first:
        raise ValueError("last_snapshot before first_snapshot")


def render(sql, params):
    for k, v in params.items():
        sql = sql.replace("{{" + k + "}}", str(v))
    if "{{" in sql:
        raise ValueError("unsubstituted placeholder in SQL: " + sql[sql.index("{{"):][:40])
    return sql


def connect(raw_dir, tmp_dir, memory_limit="8GB", threads=None):
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{tmp_dir}'")
    con.execute("SET preserve_insertion_order=false")
    if threads:
        con.execute(f"SET threads={int(threads)}")
    for n in RAW_NAMES:
        files = f"{Path(raw_dir) / n}/part-*.parquet"
        con.execute(f"CREATE OR REPLACE VIEW raw_{n} AS SELECT * FROM read_parquet('{files}', union_by_name=true)")
    return con


def build(raw_dir=None, out_dir=None, sql_dir=None, tmp_dir=None, params=None, only=None, verbose=True,
          memory_limit="8GB", threads=None):
    """Run every SQL file (or those whose stem is in `only`), then export the OUTPUTS tables."""
    raw_dir = Path(raw_dir or ROOT / "data" / "raw")
    out_dir = Path(out_dir or ROOT / "data" / "processed")
    sql_dir = Path(sql_dir or SQL_DIR)
    tmp_dir = Path(tmp_dir or ROOT / "data" / "interim" / "duckdb_tmp")
    p = {**DEFAULTS, **(params or {})}
    check_params(p)
    con = connect(raw_dir, tmp_dir, memory_limit, threads)
    timings = {}
    for f in sorted(sql_dir.glob("[0-9][0-9]_*.sql")):
        if only and f.stem not in only:
            continue
        t0 = time.time()
        con.execute(render(f.read_text(), p))
        timings[f.stem] = round(time.time() - t0, 1)
        if verbose:
            print(f"{f.stem}: {timings[f.stem]}s", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for name in OUTPUTS:
        if name in have:
            con.execute(f"COPY {name} TO '{out_dir / (name + '.parquet')}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    info = dict(params=p, timings_s=timings, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    (out_dir / "build_info.json").write_text(json.dumps(info, indent=2))
    return con
