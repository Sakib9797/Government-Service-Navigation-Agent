"""
Validate data/taxonomy.json.

Run this after any taxonomy edit. It enforces the invariants the rest of the
system assumes: ids are unique and stable, aliases are unambiguous (an alias
matching two categories would make keyword fallback non-deterministic), and
every referenced source id actually exists and was reachable in the audit.

Exit code 1 on error, 0 if only warnings.
"""
import json
import re
import sys

TAX = "data/taxonomy.json"
AUDIT = "data/source_audit.json"

errors, warnings = [], []


def main():
    tax = json.load(open(TAX, encoding="utf-8"))
    cats = tax["categories"]

    audit = {r["id"]: r for r in json.load(open(AUDIT, encoding="utf-8"))["results"]}

    # 1. ids: unique, and safe to use as a metadata filter value / filename
    ids = [c["id"] for c in cats]
    for i in ids:
        if len(ids) != len(set(ids)) and ids.count(i) > 1:
            errors.append(f"duplicate category id: {i}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", i):
            errors.append(f"id not snake_case: {i}")
    for reserved in tax["fallbacks"]:
        if reserved in ids:
            errors.append(f"id collides with a fallback: {reserved}")

    # 2. required fields
    required = ("id", "bn", "en", "office", "sources", "ingest_tier", "mvp_priority", "aliases")
    for c in cats:
        for f in required:
            if f not in c:
                errors.append(f"{c.get('id','?')}: missing field '{f}'")
        if len(c.get("aliases", [])) < 3:
            warnings.append(f"{c['id']}: only {len(c.get('aliases',[]))} aliases - thin for classifier fallback")
        if not any(re.search(r"[ঀ-৿]", a) for a in c.get("aliases", [])):
            errors.append(f"{c['id']}: no Bengali-script alias (explain.md 5.4 requires code-mixed support)")
        if not any(re.fullmatch(r"[A-Za-z0-9 .'-]+", a) for a in c.get("aliases", [])):
            warnings.append(f"{c['id']}: no romanised alias - real users type Banglish")

    # 3. aliases must not be ambiguous across categories
    seen = {}
    for c in cats:
        for a in c["aliases"]:
            k = a.lower().strip()
            if k in seen:
                errors.append(f"alias '{a}' maps to BOTH {seen[k]} and {c['id']} - classifier cannot disambiguate")
            seen[k] = c["id"]

    # 4. every referenced source must exist in the audit and have been reachable
    for c in cats:
        for s in c["sources"]:
            if s not in audit:
                errors.append(f"{c['id']}: source '{s}' not in {AUDIT}")
            elif not audit[s].get("reachable"):
                errors.append(f"{c['id']}: source '{s}' was NOT REACHABLE in the audit "
                              f"({audit[s].get('error','')[:50]})")
            elif audit[s].get("likely_js_rendered"):
                warnings.append(f"{c['id']}: source '{s}' is a JS shell - needs T3 handling, not plain HTML")
        if not c["sources"] and c["ingest_tier"] != "unmapped":
            errors.append(f"{c['id']}: no sources but ingest_tier is '{c['ingest_tier']}'")
        if not c["sources"]:
            warnings.append(f"{c['id']}: unmapped - no audited source, cannot be built yet")

    # 5. MVP coverage sanity
    p1 = [c["id"] for c in cats if c["mvp_priority"] == 1]
    if len(p1) != 5:
        warnings.append(f"{len(p1)} priority-1 categories; Step 2 plans for exactly 5")

    print(f"{len(cats)} categories, {len(tax['fallbacks'])} fallbacks, {len(seen)} unique aliases")
    print(f"priority-1 (Step 2 hand-curation set): {', '.join(p1)}")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
