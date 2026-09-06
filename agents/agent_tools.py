"""
Tools the ingestion agent may call.

Design rule: SAFETY IS ENFORCED HERE, NOT IN THE PROMPT.

A model can be talked out of an instruction; it cannot be talked out of a
function that does not exist. So:

  * `save_draft` writes only to data/drafts/ and hard-forces every record and
    every fee to verification.status = "unverified". The agent has no tool that
    can write to data/services/.
  * Only `parse_fee` can turn text into an amount, and it delegates to the same
    conservative parser used by the scrapers - the one that refuses ratios,
    instalments and table-derived pricing. The agent chooses WHERE to look;
    deterministic code decides WHAT the number is.
  * Every fetch goes through tools/polite.py, so the per-host request budget and
    back-off apply no matter what the agent decides to do.

Each tool returns a small JSON-serialisable dict. Observations are truncated,
because an agent that pastes a 200KB page into its own context stops reasoning.
"""
import json
import os
import re
import sys

sys.path.insert(0, "tools")
sys.path.insert(0, ".")

from bijoy import decode as bijoy_decode
from bn_pdf import UnsupportedEncoding, detect_encoding, extract_text, has_unmapped
from discover_links import links as _discover
from fetch_cache import fetch, visible_text
from polite import HostParked
from staleness import extract as _staleness
from textnorm import nfc

sys.path.insert(0, "scrapers")
from v2ministry import parse_fee_cell

DRAFT_DIR = "data/drafts"
MAX_OBS = 4000          # characters of observation returned to the agent


def _clip(s, n=MAX_OBS):
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n...[truncated, {len(s)} chars total]"


# --------------------------------------------------------------- tools
def discover_links(url):
    """Find candidate pages on a site, scored by service/fee vocabulary."""
    try:
        found = _discover(url)
    except HostParked as e:
        return {"error": f"host parked: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"url": url, "links": [{"score": s, "label": nfc(l)[:70], "url": u} for s, l, u in found[:25]]}


def fetch_page(url):
    """Fetch an HTML page and return its visible text plus its self-reported date."""
    try:
        r = fetch(url)
    except HostParked as e:
        return {"error": f"host parked: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    ctype = (r.get("content_type") or "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return {"url": url, "is_pdf": True, "bytes": r["bytes"],
                "note": "This is a PDF. Use detect_pdf then decode_pdf."}
    text = nfc(visible_text(r["body"].decode("utf-8", errors="replace")))
    return {"url": url, "status": r["status"], "is_pdf": False,
            "source_last_updated": _staleness(text)[0], "text": _clip(text)}


def detect_pdf(url):
    """Classify a PDF's Bengali encoding before trusting any text from it."""
    try:
        data = fetch(url)["body"]
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    kind, ratio = detect_encoding(data)
    return {"url": url, "encoding": kind, "bengali_ratio": round(ratio, 3),
            "note": {"nikosh_cmap": "Unicode Nikosh with a broken CMap - decode_pdf handles it.",
                     "legacy_bijoy": "Legacy SutonnyMJ - decode_pdf handles it.",
                     "plain": "Already-correct text.",
                     "empty": "No text layer (scanned). OCR would be needed; not wired in.",
                     "legacy_unknown": "An unrecognised legacy Bengali font. No mapping table exists - skip it.",
                     "not_a_pdf": "The server did not return a PDF (probably an HTML error page). Skip it."}.get(kind, "")}


def decode_pdf(url, contains=None):
    """Decode a PDF to text. Optionally return only lines containing `contains`."""
    try:
        data = fetch(url)["body"]
        lines = [nfc(l) for _, l in extract_text(data)]
    except UnsupportedEncoding as e:
        return {"error": f"refused: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    unusable = sum(1 for l in lines if has_unmapped(l))
    if contains:
        sel = [l for l in lines if nfc(contains) in l]
        return {"url": url, "total_lines": len(lines), "unusable_lines": unusable,
                "matched": len(sel), "lines": _clip("\n".join(sel))}
    return {"url": url, "total_lines": len(lines), "unusable_lines": unusable,
            "lines": _clip("\n".join(lines[:120]))}


def extract_tables(url):
    """Return HTML tables from a page as rows of cells."""
    try:
        html = fetch(url)["body"].decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    import urllib.parse
    out = []
    for t in re.findall(r"(?is)<table[^>]*>(.*?)</table>", html):
        rows = []
        for rm in re.finditer(r"(?is)<tr[^>]*>(.*?)</tr>", t):
            cells = [nfc(visible_text(c))[:120] for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1))]
            if not any(x.strip() for x in cells):
                continue
            # Row-level links matter: government index tables are usually
            # "topic | Download (PDF)", so the cell text alone is a dead end.
            hrefs = [urllib.parse.urljoin(url, h)
                     for h in re.findall(r'(?i)href=["\']([^"\']+)["\']', rm.group(1))]
            rows.append({"cells": cells, "links": hrefs[:3]})
        if len(rows) >= 2:
            out.append(rows[:15])
    # Trim by STRUCTURE, not by clipping a JSON string: clipping mid-string and
    # re-parsing raises JSONDecodeError on control characters.
    preview = []
    for tbl in out[:3]:
        preview.append([{"cells": [c[:80] for c in r["cells"][:6]], "links": r["links"][:2]}
                        for r in tbl[:12]])
    return {"url": url, "tables": len(out), "preview": preview}


def parse_fee(text):
    """Turn a fee cell into amounts. THE ONLY WAY the agent can produce a number.

    Delegates to the scrapers' conservative parser: it refuses ratio-based,
    instalment-based and table-derived pricing rather than guessing.
    """
    fees, note = parse_fee_cell(text or "")
    return {"input": _clip(text, 400), "fees": fees, "refused_reason": note,
            "note": "amount_bdt values here are the ONLY numbers you may put in a draft"}


def save_draft(category, service_name_en, service_name_bn, office, source_url,
               source_last_updated=None, fees=None, documents=None, steps=None,
               audience_check=None, notes=None):
    """Write a DRAFT record for human review. Never writes to data/services/."""
    if not audience_check:
        return {"error": "audience_check is required: state in one sentence whether this "
                         "document is written for CITIZENS or for government officers. "
                         "Officer manuals must not become citizen records."}
    os.makedirs(DRAFT_DIR, exist_ok=True)
    unver = {"status": "unverified", "verified_by": None, "verified_date": None,
             "method": "proposed by agents/ingestion_agent.py - NOT human verified"}
    rec = {
        "category": category,
        "service_name_en": service_name_en, "service_name_bn": service_name_bn,
        "office": office, "locality": None,
        "variants": [{"variant_id": "agent_draft", "label_en": service_name_en,
                      "label_bn": service_name_bn,
                      "required_docs": [{"doc": d, "mandatory": False, "source_url": source_url}
                                        for d in (documents or [])],
                      "steps": [{"step": s, "where": office, "source_url": source_url}
                                for s in (steps or [])]}],
        # Every fee is forced unverified regardless of what the agent passed.
        "fees": [{**f, "verification": dict(unver)} for f in (fees or [])],
        "office_location": None, "contact": None, "apply_portal": None,
        "source_url": source_url, "last_scraped_date": None,
        "source_last_updated": source_last_updated,
        "verification": dict(unver),
        "notes": ["AGENT DRAFT - requires human review before promotion to data/services/.",
                  f"Audience check by agent: {audience_check}"] + list(notes or []),
    }
    path = os.path.join(DRAFT_DIR, f"{category}.json")
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return {"saved": path, "fees": len(rec["fees"]),
            "documents": len(rec["variants"][0]["required_docs"]),
            "status": "unverified (forced)"}


def give_up(category, reason):
    """Record that no usable source was found. A correct outcome, not a failure."""
    os.makedirs(DRAFT_DIR, exist_ok=True)
    path = os.path.join(DRAFT_DIR, f"{category}.notfound.json")
    json.dump({"category": category, "reason": reason}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return {"saved": path, "reason": reason}


# ------------------------------------------------- schemas for the model
TOOLS = [
    (discover_links, "Find candidate pages on a government site, scored by service/fee vocabulary. Start here.",
     {"url": {"type": "string", "description": "Site or page URL to scan for links"}}, ["url"]),
    (fetch_page, "Fetch an HTML page: returns visible text and the page's self-reported last-updated date.",
     {"url": {"type": "string"}}, ["url"]),
    (detect_pdf, "Classify a PDF's encoding (nikosh_cmap / legacy_bijoy / plain / empty) before decoding it.",
     {"url": {"type": "string"}}, ["url"]),
    (decode_pdf, "Decode a PDF to Bengali text. Pass `contains` to return only matching lines.",
     {"url": {"type": "string"}, "contains": {"type": "string", "description": "optional filter, e.g. 'ফি'"}}, ["url"]),
    (extract_tables, "Return HTML tables from a page as rows of cells.",
     {"url": {"type": "string"}}, ["url"]),
    (parse_fee, "Convert a fee cell into amounts. The ONLY way to produce a number.",
     {"text": {"type": "string", "description": "verbatim fee cell text"}}, ["text"]),
    (save_draft, "Save a DRAFT record for human review. Requires audience_check.",
     {"category": {"type": "string"}, "service_name_en": {"type": "string"},
      "service_name_bn": {"type": "string"}, "office": {"type": "string"},
      "source_url": {"type": "string"}, "source_last_updated": {"type": "string"},
      "fees": {"type": "array", "items": {"type": "object"}},
      "documents": {"type": "array", "items": {"type": "string"}},
      "steps": {"type": "array", "items": {"type": "string"}},
      "audience_check": {"type": "string",
                         "description": "One sentence: is this document for CITIZENS or for government officers?"},
      "notes": {"type": "array", "items": {"type": "string"}}},
     ["category", "service_name_en", "service_name_bn", "office", "source_url", "audience_check"]),
    (give_up, "Record that no usable citizen-facing source was found. This is a valid outcome.",
     {"category": {"type": "string"}, "reason": {"type": "string"}}, ["category", "reason"]),
]

REGISTRY = {fn.__name__: fn for fn, _, _, _ in TOOLS}


def schemas():
    """Tool schemas in the standard {name, description, input_schema} shape."""
    return [{"name": fn.__name__, "description": desc,
             "input_schema": {"type": "object", "properties": props, "required": req}}
            for fn, desc, props, req in TOOLS]


def call(name, args):
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": f"no such tool: {name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
