"""
Parameterised scraper for the V2Ministry CMS.

Step 0 found that dip, minland, brta, dlrs, orgbdr, dncc, dscc and roc all run
the SAME government CMS: identical URL patterns, identical citizen-charter
table layout, identical self-reported update footer. So this is one scraper
driven by a per-office config, not eight bespoke ones.

Columns are located by HEADER TEXT, never by index: charters vary between 7 and
8 columns (some add a 'প্রাপ্তিস্থান' column), and index-based parsing would
silently read the fee out of the timeline column.

FEE PARSING IS DELIBERATELY CONSERVATIVE. Real charter fee cells are prose:

  "ক) মোটরসাইকেল ... ৩৪৫/-টাকা (ভ্যাটসহ) (খ) ... ৫১৮/- টাকা (ভ্যাটসহ)"   -> two labelled fees
  "স্মার্ট কার্ড অপেশাদার লাইসেন্স ২৫৪২/- টাকা (ভ্যাটসহ)"                    -> one fee
  "রেজিস্ট্রেশন ফি-এর ৩ ভাগের ১ ভাগ"                                      -> a RATIO, no absolute amount
  "সর্বমোট ফি ৯,৩১৩/- ... প্রতিকিস্তি ১১৫০/- ... অবশিষ্ট ৪৬০০/-"            -> instalments, not one price

Grabbing "the first number" from those produces a confidently wrong fee, which
explain.md 5.1 says is worse than no answer. So: extract only when the cell is
unambiguous, and otherwise emit amount_bdt=None with the raw text preserved for
a human. Every parse decision is recorded in the fee's verification.method.
"""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, "tools")
sys.path.insert(0, ".")

from fetch_cache import fetch, visible_text
from staleness import extract as staleness
from textnorm import nfc

TODAY = date.today().isoformat()
BN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Header synonyms -> canonical field. Matched by substring on the header cell.
HEADERS = {
    "service": ["সেবার নাম"],
    "method": ["সেবা প্রদান পদ্ধতি"],
    "docs": ["প্রয়োজনীয় কাগজপত্র"],
    "fee": ["সেবার মূল্য", "সেবামূল্য", "মূল্য এবং পরিশোধ"],
    "time": ["সময়সীমা"],
    "officer": ["দায়িত্বপ্রাপ্ত কর্মকর্তা"],
}

# One labelled amount: optional "ক)" label, text, then NNN/- টাকা
AMOUNT = re.compile(r"([\d০-৯][\d০-৯,\.]*)\s*/?-?\s*(?:টাকা|টাকার)")
FREE = re.compile(r"বিনামূল্যে|বিনা\s*ফিস")
# Signals that the cell is conditional/derived rather than a flat price.
# Genuine ambiguity signals only. NOT bare "তালিকা": charter cells routinely say
# "ব্যাংকের তালিকা" (list of banks to pay at), which is a payment instruction, not a
# derived price. Requiring "ফি ... তালিকা" keeps fee-schedule references while
# letting a flat, stated amount through.
AMBIGUOUS = re.compile(r"ভাগের|শতাংশ|ভিত্তি করে|কিস্তি|নির্ধারণ করা|ফি[^।\[]{0,20}তালিকা|অথবা\s*\(ii\)")
# Payment-instruction asides live in [...] and must not influence fee parsing.
ASIDE = re.compile(r"\[[^\]]*\]")


def _int(s):
    return int(s.translate(BN).replace(",", "").split(".")[0])


def parse_fee_cell(text):
    """Return (list_of_fees, note). Conservative by design - see module docstring."""
    t = nfc(re.sub(r"\s+", " ", text)).strip()
    if not t:
        return [], "empty fee cell"
    t = ASIDE.sub(" ", t).strip()      # drop "[pay at these banks...]" asides

    vat_incl = "ভ্যাটসহ" in t or "ভ্যাট সহ" in t
    vat_extra = bool(re.search(r"\d+\s*%\s*ভ্যাট", t))

    if FREE.search(t) and not AMOUNT.search(t):
        return [{"amount_bdt": 0, "label_bn": "বিনামূল্যে", "includes_vat": True,
                 "method": "cell states বিনামূল্যে with no amount"}], None

    hits = AMOUNT.findall(t)
    if not hits:
        return [], "no amount found in cell"

    if AMBIGUOUS.search(t):
        # Conditional, ratio-based or instalment pricing: refuse to pick a number.
        return [], (f"cell contains {len(hits)} amount(s) but is conditional/derived "
                    f"(ratio, instalment or table-based) - not reducible to one price")

    if len(hits) == 1:
        return [{"amount_bdt": _int(hits[0]), "label_bn": t[:180],
                 "includes_vat": True if vat_incl else (False if vat_extra else None),
                 "method": "single unambiguous amount in cell"}], None

    # Several amounts with (ক)/(খ) style labels -> one fee each.
    parts = re.split(r"\((?:[কখগঘঙচছজ]|[ivx]+)\)|(?<=\s)[কখগঘঙচছজ]\)", t)
    out = []
    for p in parts:
        m = AMOUNT.search(p)
        if m:
            out.append({"amount_bdt": _int(m.group(1)), "label_bn": p.strip()[:180],
                        "includes_vat": True if "ভ্যাটসহ" in p else (False if vat_extra else None),
                        "method": "labelled sub-item within a multi-fee cell"})
    if len(out) == len(hits):
        return out, None
    return [], f"cell contains {len(hits)} amounts that could not be split reliably"


def find_table(html):
    """The citizen-services table: the biggest table whose header we recognise."""
    best = None
    for t in re.findall(r"(?is)<table[^>]*>(.*?)</table>", html):
        rows = [[nfc(visible_text(c)) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1))]
                for rm in re.finditer(r"(?is)<tr[^>]*>(.*?)</tr>", t)]
        rows = [r for r in rows if r]
        if len(rows) < 3:
            continue
        header = rows[0]
        cols = {}
        for i, h in enumerate(header):
            for field, names in HEADERS.items():
                if any(n in h for n in names):
                    cols.setdefault(field, i)
        if "service" in cols and "fee" in cols and (best is None or len(rows) > len(best[0])):
            best = (rows, cols)
    return best


def scrape_office(cfg, classify):
    """Yield (category, service_row_dict) for one office."""
    r = fetch(cfg["charter_url"])
    html = r["body"].decode("utf-8", errors="replace")
    text = visible_text(html)
    updated = staleness(text)[0] or cfg.get("published")

    found = find_table(html)
    if not found:
        print(f"  {cfg['office_id']}: no parseable citizen-charter table (likely PDF-only)")
        return
    rows, cols = found

    def cell(row, field):
        i = cols.get(field)
        return row[i] if i is not None and i < len(row) else ""

    for row in rows[1:]:
        name = cell(row, "service")
        # Skip the "(১) (২) (৩)" column-number row and empty rows.
        if not name or re.fullmatch(r"[\(\)১-৯০-৯\s.।]*", name):
            continue
        intent = classify(name)
        cat = intent["category"]
        if cat in ("unknown_service", "out_of_scope") or cat not in cfg["accept_categories"]:
            continue
        fees, note = parse_fee_cell(cell(row, "fee"))
        yield cat, {
            "service_name_bn": name,
            "method": cell(row, "method"),
            "docs_raw": cell(row, "docs"),
            "fee_raw": cell(row, "fee"),
            "time": cell(row, "time"),
            "officer": cell(row, "officer"),
            "fees": fees,
            "fee_note": note,
            "source_url": cfg["charter_url"],
            "source_last_updated": updated,
            "office": cfg["office"],
            "apply_portal": cfg.get("apply_portal"),
        }


def build_records(config_path="scrapers/cms_config.json", out_dir="data/services"):
    from agents.intent_classifier import classify
    cfgs = json.load(open(config_path, encoding="utf-8"))["offices"]
    grouped = {}
    for cfg in cfgs:
        print(f"\n[{cfg['office_id']}] {cfg['charter_url'][:76]}")
        for cat, row in scrape_office(cfg, classify):
            grouped.setdefault(cat, []).append(row)
            n = len(row["fees"])
            print(f"    {cat:<22} {n} fee(s){'  [' + row['fee_note'][:52] + ']' if row['fee_note'] else ''}"
                  f"  <- {row['service_name_bn'][:34]}")

    written = []
    for cat, rows in grouped.items():
        rec = to_record(cat, rows)
        p = os.path.join(out_dir, f"{cat}.json")
        json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        written.append((p, len(rec["fees"]), sum(len(v["required_docs"]) for v in rec["variants"])))
    return written


def to_record(category, rows):
    """Fold the scraped charter rows for one category into a service record."""
    first = rows[0]
    variants, fees = [], []
    for i, row in enumerate(rows):
        docs = [{"doc": d, "mandatory": True, "source_url": row["source_url"]}
                for d in split_docs(row["docs_raw"])]
        steps = []
        if row["method"]:
            steps.append({"step": row["method"][:600], "where": row["office"],
                          "source_url": row["source_url"]})
        if row["time"]:
            steps.append({"step": f"Stated service time: {row['time']}", "where": row["office"],
                          "source_url": row["source_url"]})
        variants.append({"variant_id": f"charter_row_{i}", "label_en": row["service_name_bn"][:120],
                         "label_bn": row["service_name_bn"][:120],
                         "required_docs": docs, "steps": steps})

        if row["fees"]:
            for j, f in enumerate(row["fees"]):
                fees.append({
                    "fee_key": f"row{i}_{j}", "label_bn": f["label_bn"],
                    "label_en": row["service_name_bn"][:120],
                    "amount_bdt": f["amount_bdt"], "includes_vat": f["includes_vat"],
                    "source_url": row["source_url"], "source_document": None,
                    "source_last_updated": row["source_last_updated"],
                    "raw_text": row["fee_raw"][:600],
                    "verification": {"status": "source_read", "verified_by": "scrapers/v2ministry.py",
                                     "verified_date": TODAY, "method": f["method"]},
                })
        else:
            fees.append({
                "fee_key": f"row{i}_unparsed", "label_bn": row["service_name_bn"][:120],
                "label_en": row["service_name_bn"][:120],
                "amount_bdt": None, "includes_vat": None,
                "source_url": row["source_url"], "source_document": None,
                "source_last_updated": row["source_last_updated"],
                "raw_text": row["fee_raw"][:600],
                "verification": {"status": "unverified", "verified_by": None, "verified_date": None,
                                 "method": row["fee_note"] or "fee cell not parseable"},
            })

    return {
        "category": category,
        "service_name_en": category.replace("_", " ").title(),
        "service_name_bn": first["service_name_bn"][:120],
        "office": first["office"],
        "locality": None,
        "variants": variants,
        "fees": fees,
        "office_location": None,
        "contact": first["officer"][:300] or None,
        "apply_portal": first.get("apply_portal"),
        "source_url": first["source_url"],
        "last_scraped_date": TODAY,
        "source_last_updated": first["source_last_updated"],
        "verification": {"status": "source_read", "verified_by": "scrapers/v2ministry.py",
                         "verified_date": TODAY, "method": "parsed from the office citizen charter table"},
        "notes": [
            "Scraped from the V2Ministry CMS citizen charter. Columns located by header text.",
            "Fees marked unverified are ones whose charter cell is conditional, ratio-based or "
            "instalment-based; the raw cell text is kept in raw_text for a human to read.",
            "Not confirmed against a gazette/circular or with the office.",
        ],
    }


def split_docs(text):
    t = nfc(re.sub(r"\s+", " ", text)).strip()
    if not t:
        return []
    parts, expected = [], 1
    marks = []
    for m in re.finditer(r"\(?([\d০-৯]{1,2})\)", t):
        if _int(m.group(1)) == expected:
            marks.append(m.start())
            expected += 1
    if not marks:
        return [t[:400]] if len(t) > 12 else []
    bounds = marks + [len(t)]
    for i in range(len(marks)):
        p = t[bounds[i]:bounds[i + 1]].strip()
        if len(p) > 12:
            parts.append(p[:400])
    return parts


if __name__ == "__main__":
    for p, nf, nd in build_records():
        print(f"\nwrote {p}: {nf} fee entries, {nd} documents")
