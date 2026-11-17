"""Phase 5 pull: ACRIS deeds for the Bronx and Brooklyn recorded since 2018, with their legals (borough, block, lot) and parties.

    python pipelines/ingest/pull_acris.py              # resumable; skips files that exist

Master (bnx9-e6tj) is filtered to recorded_borough 2 and 3 and deed document types, recorded 2018 onward, so only a few tens of thousands of rows are
fetched; Legals (8h5j-fqxa) and Parties (636b-3b5g) are fetched for those document ids in batches. Output: data/raw/acris_{master,legals,parties}/part-*.parquet
(all strings, gitignored). Party names are stored raw only in that gitignored folder; analyses hash them and no name appears in any output.
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from nycdistress.env import load_dotenv  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
BASE = "https://data.cityofnewyork.us/resource"
DEED_TYPES = ("DEED", "DEEDO", "DEED COR")
BATCH = 400


def session():
    load_dotenv(ROOT / ".env")
    s = requests.Session()
    if os.environ.get("SOCRATA_APP_TOKEN"):
        s.headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]
    return s


def get(s, ds, params, retries=8):
    for a in range(retries):
        try:
            r = s.get(f"{BASE}/{ds}.json", params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 401, 403, 404):
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException:
            pass
        time.sleep(min(60, 3 * 2 ** a))
    raise RuntimeError(f"giving up on {ds}")


def main():
    s = session()
    (RAW / "acris_master").mkdir(parents=True, exist_ok=True)
    mpath = RAW / "acris_master" / "part-00000.parquet"
    if not mpath.exists():
        where = "recorded_borough in ('2','3') AND doc_type in (" + ",".join(f"'{t}'" for t in DEED_TYPES) + ") AND recorded_datetime >= '2018-01-01'"
        rows = []
        off = 0
        while True:
            page = get(s, "bnx9-e6tj", {"$where": where, "$order": "document_id", "$limit": 50000, "$offset": off})
            rows += page
            if len(page) < 50000:
                break
            off += 50000
        pd.DataFrame(rows).astype("string").to_parquet(mpath, index=False)
        print(f"master: {len(rows):,} deed documents", flush=True)
    ids = pd.read_parquet(mpath, columns=["document_id"]).document_id.tolist()
    for name, ds in (("legals", "8h5j-fqxa"), ("parties", "636b-3b5g")):
        d = RAW / f"acris_{name}"
        d.mkdir(parents=True, exist_ok=True)
        done = 0
        for i in range(0, len(ids), BATCH * 25):
            path = d / f"part-{i // (BATCH * 25):05d}.parquet"
            if path.exists():
                continue
            chunk = ids[i:i + BATCH * 25]
            rows = []
            for j in range(0, len(chunk), BATCH):
                sub = chunk[j:j + BATCH]
                rows += get(s, ds, {"$where": "document_id in (" + ",".join(f"'{x}'" for x in sub) + ")", "$limit": 50000})
            pd.DataFrame(rows).astype("string").to_parquet(path, index=False)
            done += len(rows)
            print(f"{name}: part {i // (BATCH * 25)} {len(rows):,} rows", flush=True)


if __name__ == "__main__":
    main()
