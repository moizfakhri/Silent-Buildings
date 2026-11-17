"""Phase 7, RAG gate E1: does retrieval over HPD violation text beat a plain SQL keyword baseline?

    python pipelines/llm_retrieval_experiment.py        # about 2 minutes, offline

Task: within one building's violation records, find the records about a condition ("no heat or hot water", "rats mice and roaches", ...).
Ground truth is STRUCTURED and independent of the text: HPD's violation order numbers, grouped into condition families by reading the
canonical wording of the 60 most common order numbers (the mapping is below). Methods: BM25 and TF-IDF cosine over the violation text with a
natural-language query (three paraphrases per condition, results averaged), versus the plain SQL baseline (ILIKE any of a hand-written keyword
list, newest first) and a random ranking. 400 random buildings, cluster bootstrap by building for the intervals.

Adoption rule, fixed before running: adopt retrieval only if BM25's mean precision@10 beats the SQL baseline by at least 0.03 and the paired 95%
interval of the difference excludes 0. Otherwise the plain SQL approach stays and RAG is not used for this purpose.
"""
import json
import time
from pathlib import Path

import numpy as np

from nycdistress.llm.biography import clean_desc
from nycdistress.llm.retrieval import Bm25, TfidfCosine, sql_keyword_rank
from nycdistress.llm.sandbox import Sandbox

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase7"
FAMILIES = {   # condition -> HPD order numbers (canonical wording read from the most common order numbers)
    "heat_hot_water": {666, 670, 577, 672},
    "mold_leaks": {550, 583, 507},
    "pests": {568, 569, 567, 566, 570},
    "lead_paint": {617, 616, 624, 623, 614, 622},
    "fire_safety": {702, 1503, 539, 526, 521, 522, 512, 513, 700},
    "gas_electric": {742, 688, 689},
    "plumbing": {579, 649, 598, 593, 596, 591},
    "doors_windows_locks": {501, 530, 790, 529},
}
QUERIES = {
    "heat_hot_water": ["no heat or hot water", "heating problems apartments are cold", "hot water not working"],
    "mold_leaks": ["mold and water leaks", "damp ceiling leaking", "roof leak"],
    "pests": ["rats mice and roaches", "pest infestation", "bedbugs vermin"],
    "lead_paint": ["peeling lead paint hazard", "lead based paint", "lead hazard children"],
    "fire_safety": ["fire escape blocked or defective", "smoke or carbon monoxide detector missing", "fire safety hazards"],
    "gas_electric": ["gas supply problems", "unsafe electrical wiring", "no electric power in apartment"],
    "plumbing": ["broken sink or faucet", "toilet not flushing", "plumbing fixture repair"],
    "doors_windows_locks": ["broken door lock", "window guards missing", "defective windows and doors"],
}
KEYWORDS = {   # what a person writing SQL would use
    "heat_hot_water": ["HEAT", "HOT WATER"], "mold_leaks": ["MOLD", "LEAK"], "pests": ["ROACH", "MICE", "RATS", "VERMIN", "BEDBUG", "INFEST"],
    "lead_paint": ["LEAD"], "fire_safety": ["FIRE ESCAPE", "SMOKE DETECTOR", "CARBON MONOXIDE", "FIRE EGRESS"], "gas_electric": ["GAS", "ELECTRIC", "WIRING"],
    "plumbing": ["FAUCET", "SINK", "WASH BASIN", "WATER CLOSET", "FLUSH"], "doors_windows_locks": ["LOCK", "WINDOW", "DOOR"],
}
K = 10
METHODS = ["bm25", "tfidf", "sql_keywords", "random"]


def metrics(ranked_relevance, n_rel):
    """ranked_relevance: 0/1 list of the top-K retrieved. Returns precision@K and reciprocal rank."""
    rel = np.array(ranked_relevance[:K], dtype=float)
    p = rel.sum() / K
    first = np.flatnonzero(rel)
    return p, (1.0 / (first[0] + 1) if len(first) else 0.0)


def main(n_buildings=400, n_boot=500, seed=0):
    t0 = time.time()
    sb = Sandbox(timeout_s=120, row_limit=5_000_000)   # trusted code: the model-facing 1,000-row cap does not apply
    rng = np.random.default_rng(seed)
    corpus = [clean_desc(r[0], 400) for r in sb.run("SELECT description FROM hpd_violations USING SAMPLE 150000 ROWS")[1]]
    bm25, tfidf = Bm25().fit(corpus), TfidfCosine().fit(corpus)
    bbls = [r[0] for r in sb.run("SELECT bbl FROM building_snapshots WHERE snapshot_date = DATE '2025-10-01' AND violations_12m >= 5 ORDER BY hash(bbl) LIMIT 3000")[1]]
    rows = sb.run("SELECT bbl, violation_id, inspection_date, order_number, description FROM hpd_violations WHERE bbl IN (" + ",".join(f"'{b}'" for b in bbls) + ")")[0:2]
    by_b = {}
    for bbl, vid, d, on, desc in rows[1]:
        by_b.setdefault(bbl, []).append((vid, str(d), on, clean_desc(desc, 400)))
    eligible = [b for b, v in by_b.items() if len(v) >= 40]
    chosen = list(rng.choice(sorted(eligible), size=min(n_buildings, len(eligible)), replace=False))
    print(f"{len(chosen)} buildings, corpus {len(corpus):,} ({time.time() - t0:.0f}s)", flush=True)

    recs = []   # (building index, condition, method, precision, rr)
    for bi, b in enumerate(chosen):
        v = by_b[b]
        docs = [x[3] for x in v]
        dates = [x[1] for x in v]
        orders = np.array([x[2] for x in v])
        for cond, fam in FAMILIES.items():
            rel = np.isin(orders, list(fam))
            if rel.sum() < 3 or (~rel).sum() < 10:
                continue
            res = {}
            for name, model in (("bm25", bm25), ("tfidf", tfidf)):
                ps, rrs = [], []
                for q in QUERIES[cond]:
                    order, _ = model.rank(q, docs, K)
                    p, rr = metrics(rel[order].tolist(), rel.sum())
                    ps.append(p)
                    rrs.append(rr)
                res[name] = (np.mean(ps), np.mean(rrs))
            kw = sql_keyword_rank(KEYWORDS[cond], docs, dates, K)
            res["sql_keywords"] = metrics(rel[kw].tolist() + [0] * (K - len(kw)), rel.sum()) if kw else (0.0, 0.0)
            perm = rng.permutation(len(docs))[:K]
            res["random"] = metrics(rel[perm].tolist(), rel.sum())
            for m in METHODS:
                recs.append((bi, cond, m, *res[m]))
    n_pairs = len({(r[0], r[1]) for r in recs})
    print(f"{n_pairs} building-condition pairs evaluated ({time.time() - t0:.0f}s)", flush=True)

    arr = {m: np.array([(r[0], r[3], r[4]) for r in recs if r[2] == m]) for m in METHODS}
    bidx = arr["bm25"][:, 0].astype(int)
    nb = len(chosen)

    def agg(a, w):
        return (a[:, 1] * w).sum() / w.sum(), (a[:, 2] * w).sum() / w.sum()
    summary = {}
    point = {m: agg(arr[m], np.ones(len(arr[m]))) for m in METHODS}
    draws = {m: np.empty((n_boot, 2)) for m in METHODS}
    for i in range(n_boot):
        mult = np.bincount(rng.integers(0, nb, nb), minlength=nb).astype(float)
        w = mult[bidx]
        for m in METHODS:
            draws[m][i] = agg(arr[m], w)
    for m in METHODS:
        lo, hi = np.percentile(draws[m], [2.5, 97.5], axis=0)
        summary[m] = dict(precision_at_10=point[m][0], p_lo=lo[0], p_hi=hi[0], mrr=point[m][1], mrr_lo=lo[1], mrr_hi=hi[1])
    diffs = {}
    for m in ("bm25", "tfidf", "random"):
        d = draws[m][:, 0] - draws["sql_keywords"][:, 0]
        lo, hi = np.percentile(d, [2.5, 97.5])
        diffs[m] = dict(point=point[m][0] - point["sql_keywords"][0], lo=lo, hi=hi)
    by_cond = {}
    for cond in FAMILIES:
        by_cond[cond] = {m: float(np.mean([r[3] for r in recs if r[1] == cond and r[2] == m] or [np.nan])) for m in METHODS}
    adopt = diffs["bm25"]["point"] >= 0.03 and diffs["bm25"]["lo"] > 0
    out = dict(buildings=len(chosen), pairs=n_pairs, k=K, summary=summary, diff_vs_sql_keywords=diffs, by_condition_precision=by_cond,
               adoption_rule="BM25 precision@10 minus SQL keyword precision@10 >= 0.03 with the paired 95% interval above 0", adopt_retrieval=bool(adopt),
               seconds=round(time.time() - t0))
    (OUT / "retrieval_eval.json").write_text(json.dumps(out, indent=2, default=float))
    for m in METHODS:
        s = summary[m]
        print(f"{m:<13} precision@10 {s['precision_at_10']:.3f} [{s['p_lo']:.3f}, {s['p_hi']:.3f}]   MRR {s['mrr']:.3f}")
    for m, d in diffs.items():
        print(f"{m} minus sql_keywords: {d['point']:+.3f} [{d['lo']:+.3f}, {d['hi']:+.3f}]")
    print("ADOPT retrieval:" , adopt)


if __name__ == "__main__":
    main()
