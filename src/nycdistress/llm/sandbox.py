"""Read-only SQL sandbox for model-written queries.

Defences, in layers: (1) the database file is opened read-only; (2) DuckDB external access (files, network, extensions) is
disabled and the configuration is locked; (3) only a single SELECT statement is accepted (checked with DuckDB's own parser, plus a
deny list for defence in depth); (4) a row cap, a memory cap and a wall-clock timeout that interrupts the query.
"""
import re
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "processed" / "marts.duckdb"
DENY = re.compile(r"\b(attach|detach|copy|export|import|install|load|pragma|set|reset|call|create|alter|drop|insert|update|delete|truncate|vacuum|checkpoint|"
                  r"read_csv|read_parquet|read_json|read_text|read_blob|glob|httpfs|parquet_scan|csv_scan|sniff_csv|getenv|current_setting)\b", re.I)


class SQLRejected(Exception):
    """The statement was refused before it ran."""


class SQLError(Exception):
    """The statement ran and failed (syntax, binder, timeout, ...)."""


def validate_sql(sql):
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise SQLRejected("empty statement")
    if DENY.search(re.sub(r"'[^']*'", "''", sql)):                    # keywords inside string literals are fine
        raise SQLRejected("statement contains a forbidden keyword")
    try:
        stmts = duckdb.extract_statements(sql)
    except Exception as e:  # syntax errors surface here too
        raise SQLError(f"could not parse: {e}") from e
    if len(stmts) != 1:
        raise SQLRejected("exactly one statement is allowed")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise SQLRejected("only SELECT statements are allowed")
    return sql


class Sandbox:
    def __init__(self, db_path=None, row_limit=1000, timeout_s=20, memory="3GB", threads=4):
        self.db_path = str(db_path or DB)
        self.row_limit, self.timeout_s = row_limit, timeout_s
        self.con = duckdb.connect(self.db_path, read_only=True, config={"enable_external_access": False, "memory_limit": memory, "threads": threads})
        try:
            self.con.execute("SET lock_configuration=true")
        except duckdb.InvalidInputException as e:       # a second Sandbox on the same file in one process shares an already locked instance
            if "has been locked" not in str(e):
                raise

    def run(self, sql):
        """Return (columns, rows, truncated). Raises SQLRejected or SQLError."""
        sql = validate_sql(sql)
        timer = threading.Timer(self.timeout_s, self.con.interrupt)
        timer.start()
        try:
            cur = self.con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(self.row_limit + 1)
        except duckdb.InterruptException as e:
            raise SQLError(f"timed out after {self.timeout_s}s") from e
        except Exception as e:
            raise SQLError(str(e).splitlines()[0]) from e
        finally:
            timer.cancel()
        return cols, [tuple(r) for r in rows[: self.row_limit]], len(rows) > self.row_limit

    def close(self):
        self.con.close()
