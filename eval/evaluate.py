"""
Evaluate the GSNA pipeline.

Four scores, reported separately because they mean different things:

  1. INTENT       - did the query reach the right taxonomy category
  2. ASSERTIONS   - hand-written must_contain / must_not_contain per question
  3. GROUNDING    - **the metric that matters** (explain.md Phase 5). Every fee
                    amount and every required document printed in an answer must
                    exist verbatim in the service record. Anything else is a
                    hallucinated fee or document, which explain.md 5.1 calls
                    worse than no answer at all.
  4. SAFETY       - invariants that must hold for every answer: provenance is
                    always shown; an unverified record never prints a fee table
                    or a document checklist.

GROUNDING and SAFETY are hard gates. A build that regresses either should not
ship, regardless of the other two.

Run:  PYTHONPATH=. python eval/evaluate.py
"""
import json
import re
import sys

sys.path.insert(0, ".")
from agents.retrieval_agent import load_record
sys.path.insert(0, "tools")
from textnorm import nfc

from graph import answer

QUESTIONS = "eval/test_questions.json"
BN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# The composer now answers in the language asked, so every marker the checker
# looks for exists in two forms. Matching only the English form would let a
# Bengali answer skip the provenance gate entirely - a checker that cannot see
# a violation is worse than no checker.
MARK = {
    "fees_heading":  ("### 💰 Fees", "### 💰 ফি"),
    "docs_heading":  ("### 📄 Required documents", "### 📄 প্রয়োজনীয় কাগজপত্র"),
    "free":          ("free", "বিনামূল্যে"),
    "unverified_fee": ("not verified", "যাচাই করা হয়নি"),
    "src_updated":   ("Source last updated", "উৎস সর্বশেষ হালনাগাদ"),
    "no_details":    ("do not have verified details", "যাচাইকৃত তথ্য আমার কাছে নেই"),
    "docs_missing":  ("Not available from a verified source", "যাচাইকৃত উৎসে এখনো পাওয়া যায়নি"),
}


def has(md, key):
    # NFC on BOTH sides: the same Bengali literal typed in two source files can
    # differ in composition (য় as U+09DF vs U+09AF+U+09BC) and compare unequal
    # while looking identical. This has now bitten this project four times.
    n = nfc(md)
    return any(nfc(m) in n for m in MARK[key])


def fee_section(md):
    m = re.search(r"### 💰 Fees\n(.*?)(?=\n### |\n---|\Z)", md, re.S)
    return m.group(1) if m else ""


def doc_section(md):
    m = re.search(r"### 📄 Required documents\n(.*?)(?=\n### |\n---|\Z)", md, re.S)
    return m.group(1) if m else ""


def amounts_in_fee_table(md):
    """Every numeric amount printed in the fee table, normalised to int."""
    out = []
    for line in fee_section(md).splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Fee (BDT)" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        cell = cells[1]
        cell_n = nfc(cell)
        if any(nfc(m) in cell_n for m in MARK["free"]):
            out.append(0)
            continue
        if any(nfc(m) in cell_n for m in MARK["unverified_fee"]):
            continue
        for n in re.findall(r"(\d[\d,]*)", cell.translate(BN)):
            out.append(int(n.replace(",", "")))
    return out


def check_grounding(cat, md):
    """Return list of grounding violations for one answer."""
    rec = load_record(cat) if cat not in ("unknown_service", "out_of_scope") else None
    problems = []

    printed = set(amounts_in_fee_table(md))
    known = {f["amount_bdt"] for f in (rec or {}).get("fees", []) if f["amount_bdt"] is not None}
    for a in printed:
        if a not in known:
            problems.append(f"FEE NOT IN RECORD: {a} printed but record has {sorted(known) or 'no amounts'}")

    # Every document bullet must exist verbatim in the record.
    rec_docs = {d["doc"] for v in (rec or {}).get("variants", []) for d in v.get("required_docs", [])}
    for line in doc_section(md).splitlines():
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        if body.startswith("_"):        # the "not available" placeholder
            continue
        if not any(body[:60] in d or d[:60] in body for d in rec_docs):
            problems.append(f"DOC NOT IN RECORD: {body[:60]!r}")
    return problems


def check_safety(cat, md):
    rec = load_record(cat) if cat not in ("unknown_service", "out_of_scope") else None
    problems = []
    if rec is None:
        if has(md, "fees_heading"):
            problems.append("fee table shown for a category with no record")
        return problems

    if rec["verification"]["status"] == "unverified":
        if has(md, "fees_heading"):
            problems.append("fee table shown for an UNVERIFIED record")
        if any(re.search(re.escape(nfc(h)) + r"\n- (?!_)", nfc(md)) for h in MARK["docs_heading"]):
            problems.append("document checklist shown for an UNVERIFIED record")
    if rec["source_url"] not in md:
        problems.append("source_url missing from answer")
    if not has(md, "src_updated") and not has(md, "no_details"):
        problems.append("source date missing from answer")
    return problems


def main():
    spec = json.load(open(QUESTIONS, encoding="utf-8"))
    qs = spec["questions"]
    rows, n_intent, n_assert, n_ground, n_safe = [], 0, 0, 0, 0
    failures = []

    for q in qs:
        out = answer(q["query"])
        cat, md = out["intent"]["category"], out["answer"]

        intent_ok = cat == q["expect_category"]
        a_problems = []
        for s in q.get("must_contain", []):
            if nfc(s).lower() not in nfc(md).lower():
                a_problems.append(f"missing {s!r}")
        for s in q.get("must_not_contain", []):
            if nfc(s).lower() in nfc(md).lower():
                a_problems.append(f"present but forbidden {s!r}")
        g_problems = check_grounding(cat, md)
        s_problems = check_safety(cat, md)

        n_intent += intent_ok
        n_assert += not a_problems
        n_ground += not g_problems
        n_safe += not s_problems
        rows.append((q["id"], q["kind"], intent_ok, not a_problems, not g_problems, not s_problems))
        if not (intent_ok and not a_problems and not g_problems and not s_problems):
            failures.append((q, cat, intent_ok, a_problems, g_problems, s_problems))

    n = len(qs)
    print(f"\n{'id':<6}{'kind':<15}{'intent':<8}{'assert':<8}{'ground':<8}{'safe':<6}")
    print("-" * 52)
    for r in rows:
        print(f"{r[0]:<6}{r[1]:<15}{'ok' if r[2] else 'FAIL':<8}{'ok' if r[3] else 'FAIL':<8}"
              f"{'ok' if r[4] else 'FAIL':<8}{'ok' if r[5] else 'FAIL':<6}")

    print(f"\n{'='*52}\nRESULTS over {n} questions")
    print(f"  intent accuracy      {n_intent}/{n}  ({n_intent/n:.0%})")
    print(f"  assertions passed    {n_assert}/{n}  ({n_assert/n:.0%})")
    print(f"  GROUNDING (hard)     {n_ground}/{n}  ({n_ground/n:.0%})   "
          f"hallucination rate {1-n_ground/n:.1%}")
    print(f"  SAFETY (hard)        {n_safe}/{n}  ({n_safe/n:.0%})")

    if failures:
        print(f"\n--- {len(failures)} question(s) with issues ---")
        for q, cat, i_ok, a, g, s in failures:
            print(f"\n[{q['id']}] {q['query'][:64]}")
            if not i_ok:
                print(f"   intent: expected {q['expect_category']}, got {cat}")
            for p in a:
                print(f"   assert: {p}")
            for p in g:
                print(f"   GROUND: {p}")
            for p in s:
                print(f"   SAFETY: {p}")

    print("\nNOTE: this measures faithfulness to the published source, not")
    print("real-world correctness. Phase 5 real-world verification is still owed.")
    # Hard gates only.
    return 1 if (n_ground < n or n_safe < n) else 0


if __name__ == "__main__":
    sys.exit(main())
