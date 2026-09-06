"""
Decode the catalogued government PDFs and report what each one usefully contains.

Purpose: the HTML sources left real gaps -- birth_registration has no document
checklist, land_record has no fee amount, and the passport fees are from 2020.
Those offices all publish PDFs. This sweeps them, classifies the encoding, and
scores each for fee/document content so a human knows which are worth reading.

It reports; it does not write service records. Anything that reaches a record
still goes through the conservative fee parser and a verification status.
"""
import json
import re
import sys

sys.path.insert(0, "tools")
sys.path.insert(0, ".")

from bn_pdf import UnsupportedEncoding, detect_encoding, extract_text
from fetch_cache import fetch
from polite import HostParked
from textnorm import nfc

INDEX = "data/pdf_index.json"

FEE_WORDS = ["টাকা", "ফি", "বিনামূল্যে", "মূল্য", "চার্জ", "ভ্যাট"]
DOC_WORDS = ["কাগজপত্র", "প্রয়োজনীয়", "সনদ", "আবেদন", "দলিল", "ফরম"]
AMOUNT = re.compile(r"[\d০-৯][\d০-৯,]*\s*/?-?\s*(?:টাকা|টাকার)")


def sweep(offices, limit_per_office=4):
    idx = json.load(open(INDEX, encoding="utf-8"))
    results = []
    for off in offices:
        for url in idx.get(off, [])[:limit_per_office]:
            row = {"office": off, "url": url}
            try:
                data = fetch(url)["body"]
            except HostParked as e:
                row.update(status=f"parked: {e}")
                results.append(row)
                continue
            except Exception as e:
                row.update(status=f"{type(e).__name__}: {str(e)[:60]}")
                results.append(row)
                continue

            row["bytes"] = len(data)
            kind, ratio = detect_encoding(data)
            row["encoding"] = kind
            try:
                lines = [nfc(l) for _, l in extract_text(data)]
            except UnsupportedEncoding as e:
                row.update(status="REFUSED", note=str(e)[:70])
                results.append(row)
                continue
            except Exception as e:
                row.update(status=f"decode error: {type(e).__name__}")
                results.append(row)
                continue

            text = "\n".join(lines)
            row.update(status="ok", lines=len(lines), chars=len(text),
                       fee_words=sum(text.count(w) for w in FEE_WORDS),
                       doc_words=sum(text.count(w) for w in DOC_WORDS),
                       amounts=len(AMOUNT.findall(text)),
                       head=" / ".join(l for l in lines[:3])[:110])
            results.append(row)
    return results


if __name__ == "__main__":
    offices = sys.argv[1:] or ["dip", "orgbdr", "dlrs"]
    rows = sweep(offices)
    print(f"\n{'office':<9}{'enc':<15}{'status':<10}{'lines':>6}{'fee':>5}{'doc':>5}{'amt':>5}  head")
    print("-" * 108)
    for r in rows:
        print(f"{r['office']:<9}{r.get('encoding','-'):<15}{r['status'][:9]:<10}"
              f"{r.get('lines',0):>6}{r.get('fee_words',0):>5}{r.get('doc_words',0):>5}"
              f"{r.get('amounts',0):>5}  {r.get('head') or r.get('note','')}")
    good = [r for r in rows if r["status"] == "ok" and r.get("amounts", 0)]
    print(f"\n{len(rows)} PDFs swept; {len(good)} contain parseable amounts")
    for r in good:
        print(f"   {r['amounts']:>3} amount(s)  {r['office']:<8} {r['url'][-52:]}")
