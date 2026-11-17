import importlib.util
import json
import re
from pathlib import Path

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location(
    "pull_socrata", Path(__file__).resolve().parents[1] / "pipelines" / "ingest" / "pull_socrata.py")
ps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ps)


class FakeResp:
    def __init__(self, data, code=200):
        self.data, self.status_code, self.text = data, code, "err"

    def json(self):
        return self.data


class FakeSession:
    """Serves N rows in :id order; understands `:id > 'x'`, `key = n`, $limit and $select."""

    def __init__(self, n, fail_first=0):
        # ids are deliberately NOT in numeric order of v, to prove paging follows :id
        self.rows = [{":id": f"row-{i:04d}", ":version": "v", "v": str(1000 - i)} for i in range(n)]
        self.calls, self.fail_first = [], fail_first

    def get(self, url, params, timeout):
        self.calls.append(params)
        if self.fail_first:
            self.fail_first -= 1
            return FakeResp(None, 503)
        where, rows = params.get("$where", ""), self.rows
        if m := re.search(r":id > '([^']+)'", where):
            rows = [r for r in rows if r[":id"] > m.group(1)]
        if m := re.search(r"\bv = (\d+)", where):
            return FakeResp([{":id": r[":id"], "v": r["v"]} for r in self.rows if r["v"] == m.group(1)])
        return FakeResp([dict(r) for r in rows[:params["$limit"]]])


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "RAW", tmp_path)
    monkeypatch.setattr(ps, "PAGE", 3)
    monkeypatch.setattr(ps.time, "sleep", lambda s: None)
    return tmp_path


def read_all(d):
    return pd.concat([pd.read_parquet(p) for p in sorted(d.glob("part-*.parquet"))])


def test_full_pull_keyset_no_gaps_no_dupes(raw):
    s = FakeSession(8)
    assert ps.pull("t", {"id": "x", "where": None}, session=s) == 8
    df = read_all(raw / "t")
    assert sorted(df.v) == sorted(str(1000 - i) for i in range(8))
    assert df.columns.tolist() == ["v"]  # system columns dropped
    assert (raw / "t" / "part-00002.cursor").read_text() == "row-0007"
    man = json.loads((raw / "t" / "_manifest.json").read_text())
    assert man["rows"] == 8 and man["parts"] == 3 and man["paging"] == "keyset(:id)" and man["complete"]
    assert all(p["$select"] == ":*,*" and p["$order"] == ":id" for p in s.calls)
    assert not list((raw / "t").glob("*.tmp"))


def test_where_is_combined_with_cursor(raw):
    s = FakeSession(5)
    ps.pull("t", {"id": "x", "where": "boroid in ('2','3')"}, session=s)
    assert s.calls[0]["$where"] == "(boroid in ('2','3'))"
    assert s.calls[1]["$where"] == "(boroid in ('2','3')) AND :id > 'row-0002'"


def test_resume_after_kill_between_cursor_and_rename(raw):
    s = FakeSession(8)
    ps.pull("t", {"id": "x", "where": None}, limit_pages=2, session=s)
    d = raw / "t"
    (d / "part-00002.cursor").write_text("row-0007")  # crash: cursor written, part never landed
    (d / "part-00002.parquet.tmp").write_text("junk")
    ps.pull("t", {"id": "x", "where": None}, session=FakeSession(8))
    df = read_all(d)
    assert len(df) == 8 and df.v.is_unique


def test_legacy_parts_bridge(raw, monkeypatch):
    d = raw / "hpd_violations"
    d.mkdir()
    # offset-era part: first 3 rows in :id order, no cursor sidecar, no :id column
    pd.DataFrame({"v": ["1000", "999", "998"]}).astype("string").to_parquet(d / "part-00000.parquet")
    monkeypatch.setitem(ps.LEGACY_KEYS, "hpd_violations", "v")
    s = FakeSession(8)
    ps.pull("hpd_violations", {"id": "x", "where": None}, session=s)
    df = read_all(d)
    assert len(df) == 8 and df.v.is_unique


def test_non_retryable_http_error_fails_fast(raw):
    class Bad(FakeSession):
        def get(self, url, params, timeout):
            self.calls.append(params)
            return FakeResp(None, 400)

    s = Bad(3)
    with pytest.raises(RuntimeError, match="not retryable"):
        ps.pull("t", {"id": "x", "where": None}, session=s)
    assert len(s.calls) == 1


def test_transient_503_is_retried(raw):
    s = FakeSession(4, fail_first=2)
    assert ps.pull("t", {"id": "x", "where": None}, session=s) == 4


def test_nested_geometry_is_stored_as_json_not_python_repr(raw):
    class Geo(FakeSession):
        def get(self, url, params, timeout):
            self.calls.append(params)
            rows = [{":id": f"row-{i}", "bin": str(i), "the_geom": {"type": "Point", "coordinates": [-73.9, 40.7]}, "tags": [1, 2]} for i in range(2)]
            return FakeResp(rows if "$where" not in params else [])
    ps.pull("g", {"id": "x", "where": None}, session=Geo(0))
    df = read_all(raw / "g")
    assert json.loads(df.the_geom.iloc[0]) == {"type": "Point", "coordinates": [-73.9, 40.7]}      # valid JSON (double quotes)
    assert "'" not in df.the_geom.iloc[0] and json.loads(df.tags.iloc[0]) == [1, 2]
