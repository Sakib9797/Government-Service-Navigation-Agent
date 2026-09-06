"""
Extract a page's SELF-DECLARED last-updated date.

Why this exists: explain.md's schema only carries `last_scraped_date`. Scraping
a page today stamps it 2026-09-04 and it looks fresh -- even when the page
itself says the content was last updated in 2020. The passport fee page is
exactly this case. Freshness must be measured on the CONTENT date, not the
fetch date, or the Freshness Agent gives false reassurance on the single
most expensive field in the system (fees).

Returns (iso_date_or_None, raw_string, source_of_date).
"""
import re

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

BN_MONTHS = {
    "জানুয়ারী": 1, "জানুয়ারি": 1, "ফেব্রুয়ারী": 2, "ফেব্রুয়ারি": 2, "মার্চ": 3,
    "এপ্রিল": 4, "মে": 5, "জুন": 6, "জুলাই": 7, "আগস্ট": 8, "আগষ্ট": 8,
    "সেপ্টেম্বর": 9, "অক্টোবর": 10, "নভেম্বর": 11, "ডিসেম্বর": 12,
}

PATTERNS = [
    # V2Ministry CMS footer: "কনটেন্টটি শেষ হাল-নাগাদ করা হয়েছে: সোমবার, ২০ জানুয়ারী, ২০২০"
    (r"হাল[\s​‌‍-]*নাগাদ[^:]*:\s*([^\n]{0,60}?)(?:\s+এ\s|$)", "cms_footer"),
    # In-content English marker: "Last updated: 19 জানুয়ারী 2020"
    (r"Last updated[:\s]*([০-৯\d]{1,2}\s+\S+\s+[০-৯\d]{4})", "content_marker"),
]


def parse_bn_date(s):
    s = s.translate(BN_DIGITS)
    m = re.search(r"(\d{1,2})\s*,?\s*([^\s,]+)\s*,?\s*(\d{4})", s)
    if not m:
        return None
    day, month_raw, year = m.group(1), m.group(2), m.group(3)
    month = BN_MONTHS.get(month_raw)
    if month is None:
        for name, num in BN_MONTHS.items():
            if month_raw.startswith(name[:4]):
                month = num
                break
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def extract(text):
    for pat, kind in PATTERNS:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).strip()
            return parse_bn_date(raw), raw, kind
    return None, None, None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "tools")
    from fetch_cache import fetch, visible_text
    for u in sys.argv[1:]:
        t = visible_text(fetch(u)["body"].decode("utf-8", errors="replace"))
        iso, raw, kind = extract(t)
        print(f"{iso or 'UNKNOWN':<12} {kind or '-':<16} {raw or ''}  <- {u[:70]}")
