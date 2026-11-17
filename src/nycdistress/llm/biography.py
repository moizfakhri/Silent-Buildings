"""Building biographies with record-id citations and a verifier pass.

Evidence is gathered with deterministic SQL (read-only sandbox). Every evidence record gets an id such as `viol:12345678` or
`snap:3012340001:2025-10-01`. A biography is a few sentences; every sentence that states a fact must cite the ids that support it,
in square brackets before the final period. The verifier checks: citations exist, every number in a sentence appears in a cited
record, no uncited factual sentence, and no blame language. A language model may write the text; the verifier is code.
"""
import json
import re

CITE = re.compile(r"\[([^\[\]]*)\]")
NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
DISCLAIMER = "Model estimates are for research and are not findings about any owner or tenant."
ALLOWED_UNCITED = {DISCLAIMER}
# numbers that are part of fixed wording, not statistics: "12 months" (the window length) and "311" (the service name)
BOILERPLATE_NUMBERS = re.compile(r"\b12[- ]months?\b|\bnext 12\b|\bprior 12\b|\b311(?=\s+(?:housing|requests?|service|calls?))", re.I)
APT = re.compile(r"\s*\b(?:LOCATED\s+)?AT\s+APT\b.*$|\s+IN THE (?:ENTIRE )?APARTMENT.*$", re.I)
POLICY = re.compile(r"\b(owner|owners|landlord|landlords|slumlord|negligent|negligence|neglect|neglected|blame|blamed|culpable|fault|guilty)\b", re.I)
SYSTEM = """You write a short factual biography (at most 8 sentences) of one NYC residential building from the evidence records you are given.
Rules: (1) every sentence except the final disclaimer must end with its citations in square brackets BEFORE the period, e.g. "... had 12 open violations [snap:301:2025-10-01]."
(2) cite only ids that appear in the evidence; (3) every number you write must appear in a record you cite; (4) do not speculate, do not assign blame, do not mention owners or landlords;
(5) model scores are estimates for research: say so; (6) finish with exactly this sentence, uncited: "{disclaimer}"
"""


def clean_desc(text, n=160):
    """Violation text without the apartment-level location (finer than a building biography needs)."""
    t = APT.sub("", str(text)).strip()
    t = t.replace("[", "(").replace("]", ")")                 # square brackets are reserved for citations
    t = re.sub(r"\.\s+(?=[A-Z\[(])", "; ", t)                   # a period inside the text would split the sentence for the verifier
    return t[:n].rstrip(". ")


def _q(sb, sql, params=()):
    s = sql
    for p in params:
        s = s.replace("?", "'" + str(p).replace("'", "''") + "'", 1)
    return sb.run(s)[1]


def gather(sb, bbl, snapshot="2025-10-01", k_viol=6, strategy="sql", query=None, retriever=None):
    """Evidence for one building as {id: {"kind": str, "text": str, "values": dict}}."""
    ev = {}
    b = _q(sb, "SELECT borough, community_district, units_residential, year_built, building_class, floors FROM buildings WHERE bbl = ?", [bbl])
    if not b:
        raise KeyError(f"unknown building {bbl}")
    bo, cd, units, yb, cls, floors = b[0]
    ev[f"bld:{bbl}"] = {"kind": "building", "text": f"Lot {bbl}, {bo}, community district {cd}, {units} residential units, built {yb}, class {cls}, {floors} floors",
                        "values": dict(bbl=bbl, borough=bo, community_district=cd, units=units, year_built=yb, building_class=cls, floors=floors)}
    s = _q(sb, f"""SELECT predicted_risk, predicted_condition, complaint_gap, open_violations, violations_12m, class_c_violations_12m, complaint_problems_12m, requests_311_12m,
                          evictions_12m, dob_violations_12m, prior_omo_charges, prior_litigations, prior_vacate_orders, prior_aep_selections, no_access_share_12m,
                          gap_top_decile, access_blocked FROM building_snapshots WHERE bbl = ? AND snapshot_date = DATE '{snapshot}'""", [bbl])
    if s:
        keys = ["risk", "condition", "gap", "open_violations", "violations_12m", "class_c_violations_12m", "complaint_problems_12m", "requests_311_12m", "evictions_12m",
                "dob_violations_12m", "prior_omo_charges", "prior_litigations", "prior_vacate_orders", "prior_aep_selections", "no_access_share", "gap_top_decile", "access_blocked"]
        v = dict(zip(keys, s[0]))
        v["risk_pct"] = None if v["risk"] is None else round(100 * v["risk"], 1)
        v["condition_pct"] = None if v["condition"] is None else round(100 * v["condition"], 2)
        v["no_access_pct"] = None if v["no_access_share"] is None else round(100 * v["no_access_share"])
        v["date"] = snapshot
        ev[f"snap:{bbl}:{snapshot}"] = {"kind": "snapshot", "text": f"Snapshot {snapshot}: " + ", ".join(f"{k}={x}" for k, x in v.items()), "values": v}
    if strategy == "retrieval":
        rows = _q(sb, f"SELECT violation_id, inspection_date, violation_class, order_number, description, status FROM hpd_violations WHERE bbl = ? AND inspection_date <= DATE '{snapshot}'", [bbl])
        rows = [r for r in rows if not POLICY.search(str(r[4]))]
        if rows:
            order, _ = retriever.rank(query or "serious hazard no heat hot water mold vermin lead fire gas collapse", [r[4] for r in rows], k_viol)
            rows = [rows[i] for i in order]
    else:   # the SQL-only baseline: class C first, then newest
        rows = _q(sb, f"""SELECT violation_id, inspection_date, violation_class, order_number, description, status FROM hpd_violations
                          WHERE bbl = ? AND inspection_date <= DATE '{snapshot}'
                          ORDER BY CASE violation_class WHEN 'C' THEN 0 WHEN 'B' THEN 1 ELSE 2 END, inspection_date DESC, violation_id LIMIT {k_viol + 30}""", [bbl])
        # records whose own text speaks of owners (registration violations) stay out: the biography never frames anyone as at fault
        rows = [r for r in rows if not POLICY.search(str(r[4]))][:k_viol]
    for vid, d, cl, on, desc, st in rows:
        ev[f"viol:{vid}"] = {"kind": "violation", "text": f"HPD violation {vid} class {cl} inspected {d}: {clean_desc(desc)}", "values": dict(date=str(d), violation_class=cl, order_number=on, status=st, description=clean_desc(desc))}
    for oid, d, wt in _q(sb, f"SELECT omo_id, created_date, work_type FROM omo_charges WHERE bbl = ? AND created_date <= DATE '{snapshot}' ORDER BY created_date DESC LIMIT 2", [bbl]):
        ev[f"omo:{oid}"] = {"kind": "omo", "text": f"Emergency repair charge {oid} created {d}, work type {wt}", "values": dict(date=str(d), work_type=wt)}
    for lid, d, ct in _q(sb, f"SELECT litigation_id, opened_date, case_type FROM litigations WHERE bbl = ? AND opened_date <= DATE '{snapshot}' ORDER BY opened_date DESC LIMIT 2", [bbl]):
        ev[f"lit:{lid}"] = {"kind": "litigation", "text": f"HPD litigation {lid} opened {d}, type {ct}", "values": dict(date=str(d), case_type=ct)}
    for num, d, reason in _q(sb, f"SELECT vacate_order_number, effective_date, reason FROM vacate_orders WHERE bbl = ? AND effective_date <= DATE '{snapshot}' ORDER BY effective_date DESC LIMIT 2", [bbl]):
        ev[f"vac:{bbl}:{num}"] = {"kind": "vacate", "text": f"Vacate order {num} effective {d}, reason {reason}", "values": dict(date=str(d), reason=reason)}
    for d, rnd in _q(sb, f"SELECT start_date, aep_round FROM aep_programs WHERE bbl = ? AND start_date <= DATE '{snapshot}' ORDER BY start_date DESC LIMIT 1", [bbl]):
        ev[f"aep:{bbl}:{d}"] = {"kind": "aep", "text": f"Selected for the Alternative Enforcement Program on {d} ({rnd})", "values": dict(date=str(d), round=rnd)}
    return ev


def template_biography(ev, snapshot="2025-10-01"):
    """The deterministic evidence-only biography (the SQL-only baseline). Passes the verifier by construction."""
    bld = next(k for k in ev if k.startswith("bld:"))
    snap = next((k for k in ev if k.startswith("snap:")), None)
    b = ev[bld]["values"]
    out = [f"Lot {b['bbl']} is in {b['borough']} community district {b['community_district']}, with {b['units']} residential units, built {b['year_built']} [{bld}]."]
    if snap:
        v = ev[snap]["values"]
        out.append(f"At the {snapshot} snapshot it had {v['open_violations']} open HPD violations and {v['violations_12m']} issued in the prior 12 months, {v['class_c_violations_12m']} of them class C [{snap}].")
        out.append(f"It had {v['complaint_problems_12m']} HPD complaint problems and {v['requests_311_12m']} 311 housing requests in the prior 12 months [{snap}].")
        out.append(f"Earlier city actions: {v['prior_omo_charges']} emergency repair charges, {v['prior_litigations']} litigations, {v['prior_vacate_orders']} vacate orders and {v['prior_aep_selections']} AEP selections [{snap}].")
    for k, r in ev.items():
        if k.startswith("viol:"):
            x = r["values"]
            out.append(f"A class {x['violation_class']} violation was recorded on {x['date']}: {x['description'].rstrip('.')} [{k}].")
            if sum(1 for s in out if "violation was recorded" in s) >= 3:
                break
    if snap and ev[snap]["values"]["risk_pct"] is not None:
        v = ev[snap]["values"]
        out.append(f"A model estimates a {v['risk_pct']}% chance of an enforcement event in the next 12 months, which is a research estimate [{snap}].")
    out.append(DISCLAIMER)
    return " ".join(out)


# ------------------------------------------------------------------------------ verifier
def _numbers(text):
    vals = []
    for m in NUM.findall(text):
        t = m.rstrip("%").replace(",", "")
        try:
            vals.append((float(t), "." in t))
        except ValueError:
            pass
    return vals


def _evidence_numbers(records):
    nums = []

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            nums.append(float(v))
        else:
            for t in NUM.findall(str(v)):
                try:
                    nums.append(float(t.rstrip("%").replace(",", "")))
                except ValueError:
                    pass
    for r in records:
        walk(r["text"])
        for v in r["values"].values():
            walk(v)
    return nums


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", text.strip()) if s.strip()]


def verify(text, ev):
    """Check a biography against its evidence. Returns dict(sentences, faithfulness, issues, n_sentences)."""
    results, issues = [], []
    for s in split_sentences(text):
        if s in ALLOWED_UNCITED:
            results.append(dict(sentence=s, ok=True, problems=[]))
            continue
        probs = []
        ids = [c.strip() for grp in CITE.findall(s) for c in grp.split(",") if c.strip()]
        body = CITE.sub("", s)
        numbers_body = BOILERPLATE_NUMBERS.sub(" ", body)
        if not ids:
            probs.append("uncited")
        unknown = [i for i in ids if i not in ev]
        if unknown:
            probs.append("unknown_id:" + ",".join(unknown))
        cited = [ev[i] for i in ids if i in ev]
        if cited:
            have = _evidence_numbers(cited)
            for val, is_dec in _numbers(numbers_body):
                ok = any((abs(val - h) <= 0.051) if is_dec else (val == h) for h in have)
                if not ok:
                    probs.append(f"unsupported_number:{val:g}")
        if POLICY.search(body):
            probs.append("policy:" + POLICY.search(body).group(0).lower())
        results.append(dict(sentence=s, ok=not probs, problems=probs))
        issues += [f"{p} in: {s[:70]}" for p in probs]
    n = len(results)
    return dict(sentences=results, n_sentences=n, faithfulness=(sum(r["ok"] for r in results) / n) if n else 0.0, issues=issues,
                has_disclaimer=any(r["sentence"] == DISCLAIMER for r in results))


def evidence_prompt(ev):
    return "\n".join(f"[{k}] {r['text']}" for k, r in ev.items())


def generate_verified(client, ev, max_repairs=1):
    """Ask the model for a biography, verify it, and give it one chance to repair the listed problems."""
    system = SYSTEM.format(disclaimer=DISCLAIMER)
    user = "Evidence records:\n" + evidence_prompt(ev) + "\n\nWrite the biography."
    text = client.complete(system, user, max_tokens=700)
    v = verify(text, ev)
    attempts = 1
    while (v["issues"] or not v["has_disclaimer"]) and attempts <= max_repairs:
        text = client.complete(system, user + "\n\nYour previous draft had these problems:\n" + "\n".join(v["issues"] or ["missing final disclaimer"]) + "\nRewrite it fixing them.", max_tokens=700)
        v = verify(text, ev)
        attempts += 1
    return dict(text=text, verification=v, attempts=attempts)


def evidence_json(ev):
    return json.dumps({k: r["values"] for k, r in ev.items()}, default=str)
