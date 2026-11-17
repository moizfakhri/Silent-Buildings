import sys
import types

import duckdb
import pytest

from nycdistress.llm import client as cl
from nycdistress.llm.gold import GOLD
from nycdistress.llm.sandbox import DB, Sandbox, SQLError, SQLRejected, validate_sql
from nycdistress.llm.schema import TABLES, schema_text
from nycdistress.llm.text2sql import build_system, evaluate, extract_sql, results_match

needs_marts = pytest.mark.skipif(not DB.exists(), reason="marts.duckdb not built (python pipelines/build_marts.py)")


@pytest.fixture(scope="module")
def sb():
    s = Sandbox(timeout_s=8)
    yield s
    s.close()


# ---------------------------------------------------------------------------------- pure logic
def test_extract_sql_handles_fences_and_plain_text():
    assert extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("Here you go:\n```\nSELECT a FROM t\n```\nDone") == "SELECT a FROM t"
    assert extract_sql("SELECT 2;") == "SELECT 2"


def test_results_match_rules():
    assert results_match([(1.00004,)], [(1.0,)], False)                        # floats round to 4 decimals
    assert not results_match([(1.001,)], [(1.0,)], False)
    assert results_match([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], False)      # order ignored unless asked for
    assert not results_match([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], True)
    assert not results_match([(1, 2)], [(1,)], False)                          # different number of columns
    assert results_match([(True,)], [(1,)], False) and results_match([(None,)], [(None,)], False)


def test_validate_sql_accepts_selects_and_rejects_everything_else():
    assert validate_sql("SELECT 1;") == "SELECT 1"
    assert validate_sql("WITH a AS (SELECT 1 x) SELECT x FROM a").startswith("WITH")
    assert validate_sql("SELECT 'drop table x' AS s") == "SELECT 'drop table x' AS s"     # keywords inside a string literal are fine
    for bad in ["DROP TABLE buildings", "SELECT 1; SELECT 2", "CREATE TABLE x AS SELECT 1", "INSERT INTO buildings VALUES (1)", "DELETE FROM buildings",
                "COPY buildings TO '/tmp/x.csv'", "ATTACH 'x.db'", "INSTALL httpfs", "LOAD httpfs", "PRAGMA database_list", "SET memory_limit='1GB'",
                "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM read_parquet('x.parquet')", "SELECT getenv('HOME')", "UPDATE buildings SET borough = 'x'", ""]:
        with pytest.raises((SQLRejected, SQLError)):
            validate_sql(bad)


def test_schema_docs_cover_the_marts_exactly():
    text = schema_text()
    assert "building_snapshots" in text and "DATE '2025-10-01'" in text
    assert len(build_system()) > 4000 and "Question:" in build_system()
    assert all(isinstance(d, tuple) and len(d) == 2 for d in TABLES.values())


def test_live_client_builds_the_request_without_a_network(monkeypatch):
    calls = {}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="```sql\nSELECT 1\n```")])

    class FakeAnthropic:
        def __init__(self, api_key):
            calls["key_given"] = bool(api_key)
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    c = cl.AnthropicClient(model="m-test")
    assert c.complete("sys", "user", max_tokens=5) == "```sql\nSELECT 1\n```"
    assert calls["model"] == "m-test" and calls["max_tokens"] == 5 and calls["system"] == "sys" and calls["messages"][0]["content"] == "user" and calls["key_given"]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(cl, "load_dotenv", lambda *_a, **_k: [])
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        cl.AnthropicClient()
    assert cl.live_key_present() is False


# ---------------------------------------------------------------------------------- sandbox on the real marts
@needs_marts
def test_sandbox_runs_selects_caps_rows_and_times_out(sb):
    cols, rows, trunc = sb.run("SELECT count(*) AS n FROM buildings")
    assert cols == ["n"] and rows == [(101749,)] and not trunc
    _, rows, trunc = Sandbox(row_limit=5).run("SELECT bbl FROM buildings")
    assert len(rows) == 5 and trunc
    with pytest.raises(SQLError, match="timed out"):
        sb.run("SELECT count(*) FROM hpd_violations a, hpd_violations b, hpd_complaints c")       # unbounded cross join
    with pytest.raises(SQLError):
        sb.run("SELECT no_such_column FROM buildings")


@needs_marts
def test_database_is_read_only_and_locked_down_even_if_validation_were_bypassed(sb):
    c = sb.con
    for stmt in ("CREATE TABLE evil AS SELECT 1", "DELETE FROM buildings", "UPDATE buildings SET borough = 'x'", "DROP TABLE buildings"):
        with pytest.raises(duckdb.Error):
            c.execute(stmt)
    with pytest.raises(duckdb.Error):
        c.execute("SELECT * FROM read_parquet('/etc/hosts')")                                    # external access is off
    with pytest.raises(duckdb.Error):
        c.execute("SET enable_external_access=true")                                             # and the configuration is locked
    assert sb.run("SELECT count(*) FROM buildings")[1] == [(101749,)]                           # untouched


# ---------------------------------------------------------------------------------- gold set and harness
def test_gold_set_is_well_formed():
    assert len(GOLD) >= 50
    assert len({g["id"] for g in GOLD}) == len(GOLD) and len({g["question"] for g in GOLD}) == len(GOLD)
    assert len({g["cat"] for g in GOLD}) >= 6
    from nycdistress.llm.text2sql import FEW_SHOT
    assert not {q for q, _ in FEW_SHOT} & {g["question"] for g in GOLD}                         # no example is also a test question


@needs_marts
def test_every_gold_query_executes_and_returns_something(sb):
    for g in GOLD:
        _, rows, _ = sb.run(g["sql"])
        assert rows, g["id"]
        assert not all(v is None for r in rows for v in r), f"gold {g['id']} returns only NULL"


@needs_marts
def test_harness_discriminates_between_perfect_wrong_and_crude_answers(sb):
    perfect = evaluate(cl.OracleStub(GOLD), GOLD, sb)
    wrong = evaluate(cl.WrongStub(), GOLD, sb)
    crude = evaluate(cl.KeywordStub(), GOLD, sb)
    assert perfect["execution_accuracy"] == 1.0 and perfect["executable"] == 1.0
    assert wrong["execution_accuracy"] == 0.0 and wrong["executable"] == 1.0
    assert 0.0 < crude["execution_accuracy"] < 0.1
    assert set(perfect["by_category"]) == {g["cat"] for g in GOLD}


@needs_marts
def test_a_failing_query_is_repaired_once_and_counted(sb):
    class Fixer:
        name = "fixer"
        def __init__(self): self.calls = 0
        def complete(self, system, user, max_tokens=0):
            self.calls += 1
            return "SELECT broken FROM" if self.calls == 1 else "SELECT count(*) FROM buildings"
    r = evaluate(Fixer(), GOLD[:1], sb, repair=True)
    assert r["execution_accuracy"] == 1.0 and r["items"][0]["repaired"]
    r2 = evaluate(Fixer(), GOLD[:1], sb, repair=False)
    assert r2["execution_accuracy"] == 0.0 and not r2["items"][0]["executed"]
