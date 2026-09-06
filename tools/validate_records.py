"""
Validate data/services/*.json against the schema, the taxonomy, and the
project's safety rules.

Schema conformance is necessary but not sufficient. The extra checks here are
the ones that stop a wrong number reaching a citizen:
  - category must exist in the taxonomy
  - no scam text may appear in a service record (it belongs in the curated table)
  - a fee with an amount must carry a source_url and a non-unverified status
  - a fee whose source page is older than STALE_DAYS must be flagged
"""
import glob
import json
import sys
from datetime import date

from jsonschema import Draft7Validator

STALE_DAYS = 90          # explain.md section 2 threshold
SCAM_WORDS = ("দালাল", "dalal", "scam", "middleman", "bribe", "ঘুষ")

errors, warns = [], []


def days_old(iso):
    if not iso:
        return None
    y, m, d = (int(x) for x in iso.split("-"))
    return (date.today() - date(y, m, d)).days


def main():
    schema = json.load(open("schema/service_record.schema.json", encoding="utf-8"))
    validator = Draft7Validator(schema)
    tax = json.load(open("data/taxonomy.json", encoding="utf-8"))
    valid_ids = {c["id"] for c in tax["categories"]} | set(tax["fallbacks"])

    files = sorted(glob.glob("data/services/*.json"))
    print(f"validating {len(files)} record(s)\n")

    for path in files:
        rec = json.load(open(path, encoding="utf-8"))
        cat = rec.get("category", "?")

        for e in sorted(validator.iter_errors(rec), key=lambda e: e.path):
            errors.append(f"{cat}: schema: {'/'.join(str(p) for p in e.path)}: {e.message[:110]}")

        if cat not in valid_ids:
            errors.append(f"{cat}: category not in taxonomy")

        blob = json.dumps(rec, ensure_ascii=False).lower()
        for w in SCAM_WORDS:
            if w.lower() in blob and "anti-dalal fact" not in blob:
                errors.append(f"{cat}: scam-related text '{w}' in a service record - belongs in agents/scam_patterns.json")

        age = days_old(rec.get("source_last_updated"))
        status = rec["verification"]["status"]
        if age is None and status != "unverified":
            warns.append(f"{cat}: no source_last_updated but status is '{status}' - freshness cannot be judged")
        elif age is not None and age > STALE_DAYS:
            warns.append(f"{cat}: record source is {age} days old (> {STALE_DAYS})")

        nfee = 0
        for f in rec.get("fees", []):
            key = f["fee_key"]
            if f["amount_bdt"] is not None:
                nfee += 1
                if f["verification"]["status"] == "unverified":
                    errors.append(f"{cat}/{key}: has an amount but status is 'unverified'")
                if not f.get("source_url"):
                    errors.append(f"{cat}/{key}: has an amount but no source_url")
                fage = days_old(f.get("source_last_updated"))
                if fage is not None and fage > STALE_DAYS:
                    warns.append(f"{cat}/{key}: fee source is {fage} days old ({f.get('source_last_updated')}) - "
                                 f"composer MUST show this date")
            if f["amount_bdt"] is None and f["verification"]["status"] != "unverified":
                errors.append(f"{cat}/{key}: no amount but status is not 'unverified'")

        docs = sum(len(v.get("required_docs", [])) for v in rec.get("variants", []))
        print(f"  {cat:<20} fees={len(rec.get('fees',[])):>2} (with amount {nfee:>2})  docs={docs:>2}  "
              f"status={status:<14} source_updated={rec.get('source_last_updated') or 'UNKNOWN'}")

    print()
    for w in warns:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"\n{len(errors)} errors, {len(warns)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
