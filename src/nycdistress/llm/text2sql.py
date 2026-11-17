"""Text-to-SQL over the marts: prompt, SQL extraction, sandboxed execution, and execution-accuracy evaluation.

Execution accuracy = the predicted query, run in the read-only sandbox, returns the same result as the reference query
(same number of columns, same values after rounding floats to 4 decimals; row order only matters when the question asks for an order).
This is a structured-data task and is not RAG.
"""
import datetime as dt
import re
from collections import defaultdict
from decimal import Decimal

from nycdistress.llm.sandbox import Sandbox, SQLError, SQLRejected
from nycdistress.llm.schema import schema_text

SYSTEM = """You write one DuckDB SQL query that answers the user's question about NYC residential buildings.
Rules: output a single SELECT statement (WITH is allowed) and nothing else, inside a ```sql fenced block. Use only the tables and columns documented below.
Never invent columns. Use DATE literals like DATE '2025-10-01'. When the question says "the latest snapshot" use snapshot_date = DATE '2025-10-01'.
For top-k questions add a deterministic tie-break (ORDER BY the measure, then the key). Do not select more columns than the question asks for.

{schema}

Examples:
{examples}"""

# few-shot examples: deliberately different from every gold question
FEW_SHOT = [
    ("How many buildings in the Bronx have a lot area above 20,000 square feet?", "SELECT count(*) FROM buildings WHERE borough = 'Bronx' AND lot_area_sqft > 20000"),
    ("What is the average predicted risk in the snapshot of 2024-01-01 for each borough?", "SELECT borough, avg(predicted_risk) FROM building_snapshots WHERE snapshot_date = DATE '2024-01-01' GROUP BY borough"),
    ("How many class A violations were inspected in 2022?", "SELECT count(*) FROM hpd_violations WHERE violation_class = 'A' AND year(inspection_date) = 2022"),
    ("Which three order numbers appear most often among class B violations?", "SELECT order_number FROM hpd_violations WHERE violation_class = 'B' GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 3"),
    ("How many distinct buildings had a litigation case opened in 2023?", "SELECT count(DISTINCT bbl) FROM litigations WHERE year(opened_date) = 2023"),
    ("How many complaint problems in the PLUMBING category were received per year since 2021? Order by year.", "SELECT year(received_date), count(*) FROM hpd_complaints WHERE major_category = 'PLUMBING' AND year(received_date) >= 2021 GROUP BY 1 ORDER BY 1"),
    ("How many Brooklyn buildings had an eviction executed in 2023?", "SELECT count(DISTINCT e.bbl) FROM evictions e JOIN buildings b USING (bbl) WHERE b.borough = 'Brooklyn' AND year(e.executed_date) = 2023"),
]


def build_system():
    ex = "\n\n".join(f"Question: {q}\n```sql\n{s}\n```" for q, s in FEW_SHOT)
    return SYSTEM.format(schema=schema_text(), examples=ex)


def extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    return sql.rstrip(";").strip()


def _norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int,)):
        return v
    if isinstance(v, (float, Decimal)):
        return round(float(v), 4)
    if isinstance(v, (dt.date, dt.datetime)):
        return str(v)
    return v


def normalise(rows):
    return [tuple(_norm(v) for v in r) for r in rows]


def results_match(pred_rows, gold_rows, ordered):
    p, g = normalise(pred_rows), normalise(gold_rows)
    if len(p) != len(g) or (p and len(p[0]) != len(g[0])):
        return False
    if ordered:
        return p == g
    key = lambda r: tuple("" if v is None else repr(v) for v in r)  # noqa: E731
    return sorted(p, key=key) == sorted(g, key=key)


def answer(client, question, sandbox, repair=True):
    """Ask the model, run its SQL. Returns dict(sql, ok, error, rows, repaired)."""
    system = build_system()
    user = f"Question: {question}"
    text = client.complete(system, user, max_tokens=700)
    sql = extract_sql(text)
    for attempt in (0, 1):
        try:
            cols, rows, _ = sandbox.run(sql)
            return dict(sql=sql, ok=True, error=None, rows=rows, repaired=attempt == 1)
        except (SQLError, SQLRejected) as e:
            err = str(e)
            if attempt == 1 or not repair:
                return dict(sql=sql, ok=False, error=err, rows=None, repaired=attempt == 1)
            text = client.complete(system, f"{user}\n\nYour previous query failed.\nQuery: {sql}\nError: {err}\nReturn a corrected single SELECT statement.", max_tokens=700)
            sql = extract_sql(text)


def evaluate(client, gold, sandbox=None, repair=True, limit=None):
    sb = sandbox or Sandbox()
    per, by_cat = [], defaultdict(list)
    for g in gold[:limit]:
        _, gold_rows, _ = sb.run(g["sql"])
        a = answer(client, g["question"], sb, repair)
        ok = bool(a["ok"] and results_match(a["rows"], gold_rows, g["ordered"]))
        per.append(dict(id=g["id"], category=g["cat"], ok=ok, executed=a["ok"], repaired=a["repaired"], error=a["error"], sql=a["sql"]))
        by_cat[g["cat"]].append(ok)
    n = len(per)
    return dict(client=client.name, n=n, execution_accuracy=sum(p["ok"] for p in per) / n, executable=sum(p["executed"] for p in per) / n,
                by_category={k: (sum(v) / len(v), len(v)) for k, v in sorted(by_cat.items())}, items=per)
