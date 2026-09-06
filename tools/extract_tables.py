"""
Pull HTML tables and fee-bearing text out of a cached page.

Citizen charters on the V2Ministry CMS are usually either an HTML <table> or
a link to a PDF. This dumps whichever is present so a human can read it before
anything is written into a service record.

Usage: python tools/extract_tables.py <url>
"""
import re
import sys

sys.path.insert(0, "tools")
from fetch_cache import fetch, visible_text

# Bengali and ASCII digits, next to a currency word.
FEE_RE = re.compile(r"[\d০-৯][\d০-৯,\.]*\s*(?:/-)?\s*(?:টাকা|টাকার|BDT|Tk\.?|৳)|(?:টাকা|BDT|Tk\.?|৳)\s*[\d০-৯][\d০-৯,\.]*", re.I)


def tables(html):
    out = []
    for tm in re.finditer(r"(?is)<table[^>]*>(.*?)</table>", html):
        rows = []
        for rm in re.finditer(r"(?is)<tr[^>]*>(.*?)</tr>", tm.group(1)):
            cells = [visible_text(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1))]
            if any(c.strip() for c in cells):
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def main(url):
    r = fetch(url)
    html = r["body"].decode("utf-8", errors="replace")
    text = visible_text(html)
    print(f"status={r['status']} bytes={r['bytes']} visible={len(text)} cached={r['from_cache']}")

    tbs = tables(html)
    print(f"\n--- {len(tbs)} table(s) ---")
    for i, rows in enumerate(tbs):
        flat = " ".join(" ".join(r) for r in rows)
        print(f"\n[table {i}] {len(rows)} rows | fee-like: {len(FEE_RE.findall(flat))}")
        for row in rows[:14]:
            print("   | " + " | ".join(c[:44] for c in row))
        if len(rows) > 14:
            print(f"   ... {len(rows)-14} more rows")

    hits = FEE_RE.findall(text)
    print(f"\n--- {len(hits)} fee-like strings in page text ---")
    for h in dict.fromkeys(hits):
        m = re.search(re.escape(h), text)
        print(f"   {h!r:>28}  ...{text[max(0,m.start()-70):m.end()+70]}...")

    pdfs = sorted(set(re.findall(r'(?i)href=["\']([^"\']+\.pdf[^"\']*)["\']', html)))
    if pdfs:
        print(f"\n--- {len(pdfs)} PDF link(s) ---")
        for p in pdfs[:10]:
            print("   ", p[:150])


if __name__ == "__main__":
    main(sys.argv[1])
