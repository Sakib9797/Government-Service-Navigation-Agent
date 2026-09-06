"""
OCR for scanned Bangladeshi government PDFs.

Last resort, used only when a document has no recoverable text at all:
  * no text layer (pure scan), or
  * subsetted fonts with cmap=0 and private-use glyph names, where no
    font-based decoding is possible (the DNCC 2016 gazette's amount columns).

SAFETY RULE, enforced here rather than left to the caller: OCR output is
ALWAYS `unverified`. Bengali numerals OCR poorly - ১/৭ and ৩/৪ confuse easily,
and a misread digit is exactly the failure explain.md 5.1 forbids. So every
result carries a per-item confidence, and `ocr_fees()` refuses to emit an
amount below HIGH_CONF. Even above it, the amount is a CANDIDATE for a human,
never a verified fee.

Crops are saved next to the results so a person can check a number against the
pixels without re-rendering the PDF.
"""
import io
import os
import re

import fitz  # pymupdf

DPI = 300                # Bengali conjuncts need resolution; 200 loses matras
HIGH_CONF = 0.80         # below this we do not report a number at all
CROP_DIR = "data/ocr_crops"
BN_DIGITS = "০১২৩৪৫৬৭৮৯"
AMOUNT = re.compile(r"[\d০-৯][\d০-৯,]{1,}")

_reader = None


def reader(langs=("bn", "en")):
    """EasyOCR reader. Lazy - model download is ~100MB on first use."""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(list(langs), gpu=False, verbose=False)
    return _reader


def render(data, page_no, dpi=DPI):
    doc = fitz.open(stream=data, filetype="pdf")
    pm = doc[page_no].get_pixmap(dpi=dpi)
    return pm.tobytes("png")


def ocr_page(data, page_no, dpi=DPI, save_crop=False, tag=""):
    """Return [(text, confidence, bbox)] for one rendered page."""
    png = render(data, page_no, dpi)
    if save_crop:
        os.makedirs(CROP_DIR, exist_ok=True)
        open(os.path.join(CROP_DIR, f"{tag or 'page'}_p{page_no + 1}.png"), "wb").write(png)
    out = []
    for box, text, conf in reader().readtext(png):
        out.append((text, float(conf), box))
    return out


def ocr_text(data, page_no, min_conf=0.0, **kw):
    return " ".join(t for t, c, _ in ocr_page(data, page_no, **kw) if c >= min_conf)


def ocr_fees(data, page_no, **kw):
    """Candidate amounts from a scanned page.

    Returns dicts shaped for the service-record fee schema, but ALWAYS with
    verification.status = 'unverified'. Nothing OCR produces is a fact until a
    person has looked at the crop.
    """
    items = ocr_page(data, page_no, save_crop=True, **kw)
    cands = []
    for text, conf, box in items:
        for m in AMOUNT.finditer(text):
            raw = m.group(0)
            digits = raw.translate(str.maketrans(BN_DIGITS, "0123456789")).replace(",", "")
            if not digits.isdigit():
                continue
            cands.append({
                "amount_candidate": int(digits),
                "raw": raw,
                "context": text[:80],
                "confidence": round(conf, 3),
                "reported": conf >= HIGH_CONF,
                "page": page_no + 1,
                "bbox": [[round(p[0]), round(p[1])] for p in box],
                "verification": {
                    "status": "unverified",
                    "verified_by": None,
                    "verified_date": None,
                    "method": f"OCR (easyocr bn+en, {DPI}dpi, confidence {conf:.2f}) - "
                              f"CANDIDATE ONLY, a human must confirm against the saved crop",
                },
            })
    return cands


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, "tools")
    from fetch_cache import fetch
    idx = json.load(open("data/pdf_index.json", encoding="utf-8"))
    url = sys.argv[1] if len(sys.argv) > 1 else [x for x in idx["dncc"] if "7a47f4d4" in x][0]
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    data = fetch(url)["body"]
    print(f"OCR page {page + 1} of {url[-40:]}")
    items = ocr_page(data, page, save_crop=True, tag="demo")
    print(f"{len(items)} text regions\n")
    for t, c, _ in items[:25]:
        flag = "  " if c >= HIGH_CONF else "LO"
        print(f"  {flag} {c:.2f}  {t[:74]}")
