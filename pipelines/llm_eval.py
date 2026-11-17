"""Phase 7 evaluation CLI.

    python pipelines/llm_eval.py                 # offline harness checks with deterministic stubs (NOT model results)
    python pipelines/llm_eval.py --live          # live evaluation with the Anthropic API; needs ANTHROPIC_API_KEY in the environment or .env
    python pipelines/llm_eval.py --live --limit 10 --n-bio 5   # a cheap smoke run

Harness mode checks that the evaluation machinery works: an oracle stub must score 100%, a wrong stub 0%, the verifier must catch corrupted
biographies. Live mode measures a real model: execution accuracy of text-to-SQL on the gold set, and the share of building biography sentences that
pass the verifier (citations exist, numbers supported, no blame language), with SQL-only evidence versus retrieval-selected evidence.
The key is never printed or written anywhere.
"""
import argparse
import json
import re
import time
from pathlib import Path

from nycdistress.llm import client as cl
from nycdistress.llm.biography import gather, generate_verified, template_biography, verify
from nycdistress.llm.gold import GOLD
from nycdistress.llm.retrieval import Bm25
from nycdistress.llm.sandbox import Sandbox
from nycdistress.llm.text2sql import evaluate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase7"


def sample_buildings(sb, n):
    return [r[0] for r in sb.run(f"SELECT bbl FROM building_snapshots WHERE snapshot_date = DATE '2025-10-01' AND units_residential > 12 ORDER BY hash(bbl) LIMIT {n}")[1]]


def harness(sb, n_bio):
    out = {"mode": "harness (deterministic stubs, NOT model results)"}
    sql = {}
    for c in (cl.OracleStub(GOLD), cl.WrongStub(), cl.KeywordStub()):
        r = evaluate(c, GOLD, sb)
        sql[c.name] = dict(execution_accuracy=r["execution_accuracy"], executable=r["executable"], n=r["n"])
        print(f"  text-to-SQL {c.name:<13} execution accuracy {r['execution_accuracy']:.3f}  executable {r['executable']:.3f}")
    out["text_to_sql"] = sql
    ok = caught = tried = unknown_caught = 0
    for bbl in sample_buildings(sb, n_bio):
        ev = gather(sb, bbl)
        t = template_biography(ev)
        ok += verify(t, ev)["faithfulness"] == 1.0
        mutated = re.sub(r"\b(\d{2,})\b", lambda m: str(int(m.group(1)) + 7), t, count=1)
        if mutated != t:
            tried += 1
            caught += bool(verify(mutated, ev)["issues"])
        unknown_caught += bool(verify(t.replace("[", "[fake:", 1), ev)["issues"])
    out["biography"] = dict(buildings=n_bio, template_fully_verified=ok, numeric_corruptions_tried=tried, numeric_corruptions_caught=caught, invented_ids_caught=unknown_caught)
    print(f"  biography template verified {ok}/{n_bio}; corrupted numbers caught {caught}/{tried}; invented ids caught {unknown_caught}/{n_bio}")
    return out


def live(sb, limit, n_bio):
    if not cl.live_key_present():
        raise SystemExit("No ANTHROPIC_API_KEY found (environment or .env). Live evaluation was not run; nothing was invented.")
    client = cl.AnthropicClient()
    out = {"mode": f"live ({client.name})", "built": time.strftime("%Y-%m-%dT%H:%M:%S")}
    r = evaluate(client, GOLD, sb, repair=True, limit=limit)
    out["text_to_sql"] = {k: r[k] for k in ("client", "n", "execution_accuracy", "executable", "by_category")}
    out["text_to_sql_items"] = [{k: v for k, v in i.items() if k != "sql"} for i in r["items"]]
    print(f"  text-to-SQL {client.name}: execution accuracy {r['execution_accuracy']:.3f} on {r['n']} questions (executable {r['executable']:.3f})")
    docs = [x[0] for x in sb.run("SELECT description FROM hpd_violations USING SAMPLE 100000 ROWS")[1]]
    bm25 = Bm25().fit(docs)
    bio = {}
    for strategy in ("sql", "retrieval"):
        faith, att, bad = [], [], 0
        for bbl in sample_buildings(sb, n_bio):
            ev = gather(sb, bbl, strategy=strategy, retriever=bm25)
            g = generate_verified(client, ev)
            faith.append(g["verification"]["faithfulness"])
            att.append(g["attempts"])
            bad += bool(g["verification"]["issues"])
        bio[strategy] = dict(buildings=len(faith), mean_sentence_faithfulness=sum(faith) / len(faith), mean_attempts=sum(att) / len(att), biographies_with_remaining_issues=bad)
        print(f"  biography ({strategy} evidence): sentence faithfulness {bio[strategy]['mean_sentence_faithfulness']:.3f}, mean attempts {bio[strategy]['mean_attempts']:.2f}, with issues {bad}/{len(faith)}")
    out["biography"] = bio
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="only the first N gold questions")
    ap.add_argument("--n-bio", type=int, default=40)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sb = Sandbox()
    res = live(sb, a.limit, a.n_bio) if a.live else harness(sb, a.n_bio)
    (OUT / ("llm_live.json" if a.live else "llm_harness.json")).write_text(json.dumps(res, indent=2, default=float))
    print("saved", "llm_live.json" if a.live else "llm_harness.json")


if __name__ == "__main__":
    main()
