"""
Find candidate service/fee pages on an audited source.

Reads a page (from cache where possible), extracts internal links with their
anchor text, and scores them against Bengali + English service vocabulary.
This is how we locate citizen charters, fee schedules and application
instructions without guessing URLs -- guessed URLs is exactly how the fake
passport-fee path got into the Step 0 candidate list.

Usage: python tools/discover_links.py <url> [more urls...]
"""
import re
import sys
import urllib.parse

sys.path.insert(0, "tools")
from fetch_cache import fetch, visible_text

# Anchor-text vocabulary that signals a page worth ingesting.
KEYWORDS = {
    "fee": 5, "fees": 5, "ফি": 5, "চার্জ": 4, "মূল্য": 3, "খরচ": 4,
    "charter": 5, "চার্টার": 5, "সিটিজেন": 4, "citizen": 3,
    "সেবা": 4, "service": 3, "services": 3,
    "আবেদন": 4, "apply": 3, "application": 3,
    "নির্দেশিকা": 4, "instruction": 3, "guideline": 3, "নিয়মাবলী": 4,
    "প্রয়োজনীয়": 4, "কাগজপত্র": 5, "document": 3, "required": 3, "দলিল": 3,
    "faq": 3, "প্রশ্ন": 3, "জিজ্ঞাসা": 3,
    "form": 2, "ফরম": 2, "প্রজ্ঞাপন": 4, "circular": 4, "পরিপত্র": 4,
    "gazette": 4, "গেজেট": 4, "notice": 2, "বিজ্ঞপ্তি": 2,
    "how": 2, "process": 3, "প্রক্রিয়া": 4, "পদ্ধতি": 4,
}


def links(url):
    r = fetch(url)
    html = r["body"].decode("utf-8", errors="replace")
    base = r["final_url"]
    host = urllib.parse.urlparse(base).netloc
    out = {}
    for m in re.finditer(r'(?is)<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html):
        href, label = m.group(1), visible_text(m.group(2))[:90]
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absu = urllib.parse.urljoin(base, href)
        p = urllib.parse.urlparse(absu)
        if p.scheme not in ("http", "https"):
            continue
        internal = p.netloc == host or p.netloc.endswith(".gov.bd")
        if not internal and not absu.lower().endswith(".pdf"):
            continue
        blob = (label + " " + absu).lower()
        score = sum(w for k, w in KEYWORDS.items() if k in blob)
        if absu.lower().endswith(".pdf"):
            score += 3          # PDFs are where fee circulars live (Tier 2)
        if score:
            prev = out.get(absu)
            if not prev or score > prev[0] or (score == prev[0] and len(label) > len(prev[1])):
                out[absu] = (score, label)
    return sorted(((s, l, u) for u, (s, l) in out.items()), reverse=True)


if __name__ == "__main__":
    for url in sys.argv[1:]:
        print(f"\n########## {url}")
        try:
            found = links(url)
        except Exception as e:
            print("  ERROR", e)
            continue
        print(f"  {len(found)} scored links")
        for s, l, u in found[:28]:
            tag = "PDF" if u.lower().endswith(".pdf") else "   "
            print(f"  {s:>3} {tag} {l[:52]:<52} {u[:96]}")
