"""
Step 7: re-fetch every source and report what drifted.

explain.md 5.5 asks for a periodic re-scrape diffed against the previous
version, to catch fee and process changes automatically. Two design calls:

1. DIFF THE EXTRACTED FACTS, NOT THE RAW HTML.
   Government pages churn on every request - view counters, session tokens,
   rotating notices, a "last visited" line. Byte-diffing them produces a change
   report on every run, which trains you to ignore it. What matters is: did the
   page's SELF-REPORTED update date move, and did any monetary amount on it
   change? Those are the two signals worth waking a human for.

2. NEVER AUTO-UPDATE A RECORD.
   explain.md 5.1 and 5.3 both require human verification before a fee reaches
   a citizen. This writes a review file and exits non-zero when something moved;
   applying the change is a person's decision.

Run:  PYTHONPATH=. python tools/rescrape.py            (report)
      PYTHONPATH=. python tools/rescrape.py --quick    (skip unchanged hosts)
"""
import glob
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, "tools")
sys.path.insert(0, ".")

import fetch_cache
from fetch_cache import fetch, visible_text
from polite import HostParked
from staleness import extract as staleness
from textnorm import nfc

REPORT_DIR = "data/drift"
BN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
AMOUNT = re.compile(r"[\d০-৯][\d০-৯,]{1,}\s*/?-?\s*(?:টাকা|টাকার)|TK\s*[\d,]+|BDT\s*[\d,]+")


def _n(s):
    d = re.sub(r"[^\d]", "", s.translate(BN))
    return int(d) if d else None


def facts_from(url, body=None):
    """The comparable facts on one page: self-reported date, amounts, text hash."""
    if body is None:
        body = fetch(url)["body"]
    text = nfc(visible_text(body.decode("utf-8", errors="replace")))
    amounts = sorted({a for a in (_n(m) for m in AMOUNT.findall(text)) if a})
    return {
        "source_last_updated": staleness(text)[0],
        "amounts": amounts,
        "text_sha1": hashlib.sha1(text.encode()).hexdigest(),
        "chars": len(text),
    }


def cached_body(url):
    """The previously stored body for a URL, or None."""
    import urllib.parse
    url = fetch_cache.to_uri(url)
    host = urllib.parse.urlparse(url).netloc
    p = os.path.join(fetch_cache.RAW, host, fetch_cache._slug(url))
    return open(p, "rb").read() if os.path.exists(p) else None


def sources_in_use():
    """Every source URL any service record depends on, with its record."""
    out = {}
    for p in sorted(glob.glob("data/services/*.json")):
        rec = json.load(open(p, encoding="utf-8"))
        urls = {rec["source_url"]}
        for f in rec.get("fees", []):
            urls.add(f["source_url"])
        for u in urls:
            out.setdefault(u, []).append(rec["category"])
    return out


def run():
    os.makedirs(REPORT_DIR, exist_ok=True)
    findings, checked, errors = [], 0, 0

    for url, cats in sorted(sources_in_use().items()):
        old_body = cached_body(url)
        before = facts_from(url, old_body) if old_body else None
        try:
            fresh = fetch(url, force=True)["body"]
        except HostParked as e:
            print(f"  parked  {url[:70]}  ({e})")
            errors += 1
            continue
        except Exception as e:
            print(f"  ERROR   {url[:70]}  {type(e).__name__}")
            errors += 1
            continue
        after = facts_from(url, fresh)
        checked += 1

        if before is None:
            print(f"  new     {url[:74]}")
            continue

        changes = []
        if before["source_last_updated"] != after["source_last_updated"]:
            changes.append({"kind": "source_date",
                            "was": before["source_last_updated"], "now": after["source_last_updated"]})
        gone = set(before["amounts"]) - set(after["amounts"])
        new = set(after["amounts"]) - set(before["amounts"])
        if gone or new:
            changes.append({"kind": "amounts", "removed": sorted(gone), "added": sorted(new)})

        if changes:
            findings.append({"url": url, "categories": cats, "changes": changes})
            print(f"  CHANGED {url[:70]}")
            for c in changes:
                print(f"            {c}")
        else:
            drift = "text changed" if before["text_sha1"] != after["text_sha1"] else "identical"
            print(f"  ok      {url[:64]}  ({drift}, no fact change)")

    stamp = datetime.now(timezone.utc).isoformat()
    report = {"run_at": stamp, "checked": checked, "errors": errors, "findings": findings,
              "note": "Facts moved. A HUMAN must verify before any record is updated - "
                      "explain.md 5.1: a wrong fee costs a real user money."}
    path = os.path.join(REPORT_DIR, f"{date.today().isoformat()}.json")
    json.dump(report, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\nchecked {checked} source(s), {errors} unreachable, {len(findings)} with fact changes")
    print(f"report: {path}")
    if findings:
        print("\nACTION REQUIRED - affected services:",
              ", ".join(sorted({c for f in findings for c in f['categories']})))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(run())
