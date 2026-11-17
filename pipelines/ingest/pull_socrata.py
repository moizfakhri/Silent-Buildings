"""Pull NYC Open Data tables to raw Parquet (all columns as strings), resumable and polite.

Usage:
    python pipelines/ingest/pull_socrata.py                 # everything in datasets.py
    python pipelines/ingest/pull_socrata.py hpd_violations  # one dataset
    python pipelines/ingest/pull_socrata.py --limit-pages 1 # smoke test (1 page each)

Output: data/raw/<name>/part-00000.parquet ... plus part-NNNNN.cursor and _manifest.json.

Paging is keyset on Socrata's system row id (`:id > last_id ORDER BY :id`), not $offset: deep
$offset queries on multi-million row tables time out. Each part's last :id is stored in a
sidecar part-NNNNN.cursor file (the :id and other system columns are not written to the parquet).
Resume: existing parts are skipped and paging continues from the last part's cursor. Parts are
written atomically (temp file, cursor, rename), so a kill never leaves a truncated part.
Env: SOCRATA_APP_TOKEN (optional, higher rate limits; also read from <root>/.env).
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

sys.path.insert(0, str(Path(__file__).parent))
from datasets import DATASETS  # noqa: E402
from nycdistress.env import load_dotenv  # noqa: E402

BASE = "https://data.cityofnewyork.us/resource"
PAGE = 50_000
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
# Parts written in the earlier $offset era have no cursor sidecar. For these datasets the cursor
# is recovered by looking up the :id of the last stored row via this (numeric, unique) column.
LEGACY_KEYS = {"hpd_violations": "violationid"}
NO_RETRY = {400, 401, 403, 404}  # malformed query / bad token: retrying cannot help


def get_json(session, url, params, retries=10):
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=120)
            if r.status_code == 200:
                return r.json()
            print(f"  HTTP {r.status_code} (attempt {attempt + 1}), backing off", flush=True)
            if r.status_code in NO_RETRY:
                raise RuntimeError(f"HTTP {r.status_code} (not retryable): {r.text[:300]}")
        except requests.RequestException as e:
            print(f"  {type(e).__name__} (attempt {attempt + 1}), backing off", flush=True)
        time.sleep(min(120, 2 ** attempt * 3))
    raise RuntimeError(f"giving up on {url}")


def get_page(session, ds_id, where, cursor, retries=10):
    """One page of rows in :id order strictly after `cursor` (None = from the start)."""
    clauses = [f"({where})"] if where else []
    if cursor:
        assert "'" not in cursor, "unexpected :id format"
        clauses.append(f":id > '{cursor}'")
    params = {"$select": ":*,*", "$order": ":id", "$limit": PAGE}
    if clauses:
        params["$where"] = " AND ".join(clauses)
    return get_json(session, f"{BASE}/{ds_id}.json", params, retries)


def legacy_cursor(session, ds_id, key, last_part):
    """:id of the last row of an old $offset-era part, found by its unique `key` value."""
    last_val = pd.read_parquet(last_part, columns=[key])[key].iloc[-1]
    found = get_json(session, f"{BASE}/{ds_id}.json",
                     {"$select": f":id,{key}", "$where": f"{key} = {int(last_val)}", "$limit": 2})
    if len(found) != 1:
        raise RuntimeError(f"cannot bridge legacy cursor: {key}={last_val} matched {len(found)} rows")
    keys = set(pd.read_parquet(last_part, columns=[key])[key])
    return found[0][":id"], key, keys


def make_session():
    s = requests.Session()
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        s.headers["X-App-Token"] = token
    return s


def pull(name, spec, limit_pages=None, session=None):
    out = RAW / name
    out.mkdir(parents=True, exist_ok=True)
    s = session or make_session()
    for f in out.glob("*.tmp"):
        f.unlink()
    for c in out.glob("part-*.cursor"):  # cursor written but its part never landed
        if not c.with_suffix(".parquet").exists():
            c.unlink()
    parts = sorted(out.glob("part-*.parquet"))
    assert [p.name for p in parts] == [f"part-{i:05d}.parquet" for i in range(len(parts))], \
        f"{name}: gap in part numbering"
    rows_total = sum(pq.ParquetFile(p).metadata.num_rows for p in parts)
    part, cursor, bridge = len(parts), None, None
    if parts:
        cf = parts[-1].with_suffix(".cursor")
        if cf.exists():
            cursor = cf.read_text().strip()
        elif name in LEGACY_KEYS:
            cursor, key, keys = legacy_cursor(s, spec["id"], LEGACY_KEYS[name], parts[-1])
            bridge = (key, keys)
            print(f"{name}: bridged {len(parts)} offset-era parts to keyset paging", flush=True)
        else:
            raise SystemExit(f"{name}: existing parts have no cursor; delete data/raw/{name}/ to repull")
    finished = bool(parts) and pq.ParquetFile(parts[-1]).metadata.num_rows < PAGE
    while not finished and not (limit_pages and part >= limit_pages):
        t0 = time.time()
        rows = get_page(s, spec["id"], spec["where"], cursor)
        if not rows:
            break
        cursor = rows[-1][":id"]
        # nested values (geometry, location) become JSON text BEFORE the string cast; astype("string") on a dict
        # would otherwise produce a Python repr with single quotes, which is not JSON
        rows = [{k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items() if not k.startswith(":")}
                for r in rows]
        df = pd.DataFrame(rows).astype("string")
        if bridge:  # first page after a legacy part must not repeat any of its rows
            key, keys = bridge
            overlap = keys & set(df[key])
            assert not overlap, f"{name}: {len(overlap)} rows overlap the legacy boundary"
            bridge = None
        final = out / f"part-{part:05d}.parquet"
        tmp = out / f"part-{part:05d}.parquet.tmp"
        df.to_parquet(tmp, index=False)
        final.with_suffix(".cursor").write_text(cursor)
        os.replace(tmp, final)
        rows_total += len(df)
        print(f"{name}: part {part} rows so far {rows_total:,} ({time.time() - t0:.0f}s)", flush=True)
        part += 1
        if len(rows) < PAGE:
            break
    (out / "_manifest.json").write_text(json.dumps(dict(
        name=name, dataset_id=spec["id"], where=spec["where"], rows=rows_total, parts=part,
        paging="keyset(:id)", last_id=cursor,
        pulled_at=datetime.now(timezone.utc).isoformat(), complete=not limit_pages), indent=2))
    return rows_total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--limit-pages", type=int)
    a = ap.parse_args()
    load_dotenv(RAW.parents[1] / ".env")  # SOCRATA_APP_TOKEN from .env if not already in the env
    print("app token:", "yes" if os.environ.get("SOCRATA_APP_TOKEN") else "no", flush=True)
    for n in a.names or DATASETS:
        pull(n, DATASETS[n], a.limit_pages)
