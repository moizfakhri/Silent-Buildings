import re

import numpy as np
import pytest

from nycdistress.llm.biography import (DISCLAIMER, clean_desc, gather, generate_verified, split_sentences, template_biography, verify)
from nycdistress.llm.retrieval import Bm25, TfidfCosine, sql_keyword_rank, tokens
from nycdistress.llm.sandbox import DB, Sandbox

needs_marts = pytest.mark.skipif(not DB.exists(), reason="marts.duckdb not built")

EV = {"bld:1": {"kind": "building", "text": "Lot 1", "values": {"units": 24, "year_built": 1928}},
      "snap:1:2025-10-01": {"kind": "snapshot", "text": "Snapshot", "values": {"open_violations": 12, "risk_pct": 7.8, "date": "2025-10-01"}},
      "viol:9": {"kind": "violation", "text": "HPD violation 9 class C inspected 2025-03-02: ABATE ROACHES", "values": {"date": "2025-03-02", "violation_class": "C"}}}


def test_a_correct_biography_passes():
    t = f"The building has 24 residential units and was built in 1928 [bld:1]. It had 12 open violations at the 2025-10-01 snapshot and a model estimate of 7.8% [snap:1:2025-10-01]. {DISCLAIMER}"
    v = verify(t, EV)
    assert v["faithfulness"] == 1.0 and not v["issues"] and v["has_disclaimer"] and v["n_sentences"] == 3


@pytest.mark.parametrize("text,expect", [
    ("The building has 25 residential units [bld:1].", "unsupported_number:25"),                      # wrong number
    ("It had 13 open violations [snap:1:2025-10-01].", "unsupported_number:13"),
    ("The building has 24 residential units [bld:999].", "unknown_id:bld:999"),                       # invented id
    ("The building has 24 residential units.", "uncited"),                                            # no citation
    ("The building has 24 residential units [snap:1:2025-10-01].", "unsupported_number:24"),          # cites the wrong record
    ("A class C violation was recorded [viol:9] for the landlord.", "policy:landlord"),               # blame language
    ("The building was neglected for years [bld:1].", "policy:neglected"),
    ("A model estimates 8.0% risk [snap:1:2025-10-01].", "unsupported_number:8"),                     # 8.0 vs 7.8 is outside rounding tolerance
])
def test_verifier_catches_each_kind_of_mistake(text, expect):
    v = verify(text + " " + DISCLAIMER, EV)
    assert any(expect in i for i in v["issues"]), (text, v["issues"])
    assert v["faithfulness"] < 1.0


def test_verifier_tolerances_and_boilerplate():
    ok = "It was inspected in the prior 12 months and had 12 open violations [snap:1:2025-10-01]."
    assert not verify(ok + " " + DISCLAIMER, EV)["issues"]                                              # "12 months" is wording, 12 is supported
    assert not verify("A model estimates 7.8% over the next 12 months [snap:1:2025-10-01]. " + DISCLAIMER, EV)["issues"]
    assert not verify("There were 311 housing requests [snap:1:2025-10-01]. " .replace("There were 311", "There were no 311") + DISCLAIMER, EV)["issues"]
    assert verify("It had 12 open violations [snap:1:2025-10-01].", EV)["has_disclaimer"] is False       # missing disclaimer is reported
    assert [len(split_sentences("A has 1.5 units [x]. B has two [y].")), split_sentences("A has 1.5 units [x]. B has two [y].")[0]] == [2, "A has 1.5 units [x]."]


def test_apartment_locations_are_removed_from_evidence_text():
    assert clean_desc("ABATE THE INFESTATION CONSISTING OF ROACHES IN THE ENTIRE APARTMENT LOCATED AT APT 23L, 23rd STORY") == "ABATE THE INFESTATION CONSISTING OF ROACHES"
    assert "APT" not in clean_desc("REPAIR THE CEILING AT APT 3, 3rd STORY, 1st APARTMENT FROM WEST")


class _Writer:
    """Fake model: first draft contains a wrong number, the repair fixes it."""
    name = "fake-writer"
    def __init__(self): self.calls = 0
    def complete(self, system, user, max_tokens=0):
        self.calls += 1
        n = 99 if self.calls == 1 else 24
        return f"The building has {n} residential units [bld:1]. {DISCLAIMER}"


def test_generate_verified_runs_one_repair_round():
    r = generate_verified(_Writer(), EV)
    assert r["attempts"] == 2 and r["verification"]["faithfulness"] == 1.0 and "24" in r["text"]
    r0 = generate_verified(_Writer(), EV, max_repairs=0)
    assert r0["attempts"] == 1 and r0["verification"]["issues"]


@needs_marts
def test_real_evidence_and_template_biographies_verify_and_mutations_are_caught():
    sb = Sandbox()
    bbls = [r[0] for r in sb.run("SELECT bbl FROM building_snapshots WHERE snapshot_date = DATE '2025-10-01' AND units_residential > 12 ORDER BY hash(bbl) LIMIT 25")[1]]
    caught = tried = 0
    for bbl in bbls:
        ev = gather(sb, bbl)
        assert f"bld:{bbl}" in ev and any(k.startswith("snap:") for k in ev)
        t = template_biography(ev)
        v = verify(t, ev)
        assert v["faithfulness"] == 1.0 and not v["issues"], (bbl, v["issues"])
        assert not re.search(r"\bAPT\b", t)                                                  # no apartment-level locations
        mutated = re.sub(r"\b(\d{2,})\b", lambda m: str(int(m.group(1)) + 7), t, count=1)    # corrupt the first multi-digit number
        if mutated != t:
            tried += 1
            caught += bool(verify(mutated, ev)["issues"])
        assert verify(t.replace("[", "[fake:", 1), ev)["issues"]                              # an invented id is always caught
    assert tried >= 20 and caught == tried                                                   # every numeric corruption is detected


@needs_marts
def test_retrieval_strategy_evidence_comes_from_the_same_building():
    sb = Sandbox()
    bbl = sb.run("SELECT bbl FROM building_snapshots WHERE snapshot_date = DATE '2025-10-01' AND violations_12m > 20 ORDER BY hash(bbl) LIMIT 1")[1][0][0]
    docs = [r[0] for r in sb.run("SELECT description FROM hpd_violations USING SAMPLE 20000 ROWS")[1]]
    ev = gather(sb, bbl, strategy="retrieval", query="mold and water leak", retriever=Bm25().fit(docs), k_viol=4)
    viol = [k for k in ev if k.startswith("viol:")]
    assert 0 < len(viol) <= 4
    ids = ",".join(k.split(":")[1] for k in viol)
    n = sb.run(f"SELECT count(*) FROM hpd_violations WHERE bbl = '{bbl}' AND violation_id IN ({ids})")[1][0][0]
    assert n == len(viol)


# ---------------------------------------------------------------------------------- retrieval
DOCS = ["ABATE THE NUISANCE CONSISTING OF MOLD AT CEILING", "ABATE THE INFESTATION CONSISTING OF ROACHES", "PROVIDE HOT WATER AT ALL FIXTURES", "REPAIR THE BROKEN LOCK ON FRONT DOOR",
        "ABATE THE INFESTATION CONSISTING OF MICE", "REPAIR THE LEAKY FAUCET AT SINK"] * 5


def test_bm25_and_tfidf_rank_relevant_documents_first():
    for model in (Bm25().fit(DOCS), TfidfCosine().fit(DOCS)):
        order, s = model.rank("mice and roaches infestation", DOCS[:6], k=2)
        assert set(order.tolist()) == {1, 4}
        assert s[order[0]] > 0 and np.allclose(model.score("zzz qqq", DOCS[:3]), 0)
    assert tokens("THE ROACHES AT APT 3") == ["roaches", "apt"]


def test_sql_keyword_baseline_is_newest_first_and_requires_a_match():
    docs = ["MOLD A", "ROACHES", "MOLD B", "MOLD C"]
    dates = ["2024-01-01", "2025-01-01", "2023-01-01", "2025-06-01"]
    assert sql_keyword_rank(["MOLD"], docs, dates, k=2) == [3, 0]
    assert sql_keyword_rank(["XYZ"], docs, dates) == []
