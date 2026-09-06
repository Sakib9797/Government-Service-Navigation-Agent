"""
Decode Bengali text from Bangladeshi government PDFs.

Two independent defects have to be fixed, in order:

1. BROKEN ToUnicode CMap.
   These PDFs (Nikosh font, produced by MS Word) ship a ToUnicode CMap whose
   entries are wrong for the most common vowel signs. Measured on NBR's 2026
   Citizen Charter: of 59 CIDs where the embedded font also carries a uniXXXX
   glyph name, 11 disagree -- and they include ি and ে, the two most frequent
   signs in Bengali. Examples:
        cid 455  CMap says 'ত'   glyph name says 'ি'
        cid 461  CMap says 'দ'   glyph name says 'ে'
        cid 437  CMap says 'ে'   glyph name says 'দ'
   The embedded font's glyph names are ground truth, so we override the CMap
   wherever a uniXXXX name exists, and fall back to the CMap otherwise (the
   conjunct glyphs -- প্র, ল্য, মূ -- have non-uniXXXX names and extract fine).

2. VISUAL vs LOGICAL ORDER.
   Even with correct codepoints the glyph stream is in rendering order, so a
   pre-base vowel sign arrives BEFORE its consonant cluster:
        ি ব ন া ম ূ ে ল ্ য     (visual)
        ব ি ন া ম ূ ল ্ য ে     (logical == বিনামূল্যে)
   reorder() walks the string and moves each pre-base sign to after the
   cluster it attaches to.

Neither fix is guesswork: (1) is read out of the font file, (2) is the Bengali
script's documented reordering rule. Nothing here infers a character.
"""
import io
import re

from fontTools.ttLib import TTFont
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1, stream_value

from pdf_cmap import font_unicode_map, parse_tounicode

# Vowel signs rendered to the LEFT of their consonant cluster.
PRE_BASE = "িেৈ"          # ি ে ৈ
# Two-part signs: ে + া = ো, ে + ৗ = ৌ. The ে half is pre-base.
SPLIT_TAIL = {"া": "ো", "ৗ": "ৌ"}
CONSONANT = re.compile(r"[ক-হৎড়-য়]")   # explicit escapes: a literal ড় may be stored decomposed, which breaks the range
VIRAMA = "্"
POST_MARKS = "ািীুূৃেৈোৌঁংঃ়ৗ"


class UnsupportedEncoding(Exception):
    """Raised rather than returning text we know is wrong."""


def has_unmapped(text):
    """True if a line still contains an undecoded glyph marker.

    A fee or document MUST NOT be extracted from such a line: '(cid:14)' is a
    character nobody decoded, and in the DNCC gazette those markers sit exactly
    in the tax-amount columns. Silently dropping them would turn '(cid:14)৫০০'
    into a confident, wrong number.
    """
    return "(cid:" in text


def corrections_for_pdf(data):
    """Return {basefont_name: {cid: correct_char}} derived from glyph names."""
    doc = PDFDocument(PDFParser(io.BytesIO(data)))
    out, seen = {}, set()
    for page in PDFPage.create_pages(doc):
        for _, v in (resolve1((page.resources or {}).get("Font")) or {}).items():
            f = resolve1(v)
            name = str(f.get("BaseFont"))
            if name in seen or "DescendantFonts" not in f or "ToUnicode" not in f:
                continue
            seen.add(name)
            try:
                df = resolve1(resolve1(f["DescendantFonts"])[0])
                fd = resolve1(df["FontDescriptor"])
                if "FontFile2" not in fd:
                    continue
                ttf = TTFont(io.BytesIO(stream_value(fd["FontFile2"]).get_data()))
                cmap = parse_tounicode(stream_value(f["ToUnicode"]).get_data())
                order = ttf.getGlyphOrder()
                byname = font_unicode_map(ttf)
                gmap = {gid: byname[n] for gid, n in enumerate(order) if n in byname}
            except Exception:
                continue
            fixes = {cid: ch for cid, ch in gmap.items() if cmap.get(cid) != ch}
            if fixes:
                out[name] = fixes
    return out


def reorder(s):
    """Visual order -> logical order for Bengali."""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch in PRE_BASE:
            # Collect the consonant cluster that follows: C (virama C)*
            j = i + 1
            if j < n and CONSONANT.match(s[j]):
                j += 1
                while j + 1 < n and s[j] == VIRAMA and CONSONANT.match(s[j + 1]):
                    j += 2
                cluster = s[i + 1:j]
                sign = ch
                # ে followed later by া / ৗ recombines into ো / ৌ
                if sign == "ে" and j < n and s[j] in SPLIT_TAIL:
                    sign = SPLIT_TAIL[s[j]]
                    j += 1
                out.append(cluster)
                out.append(sign)
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


LATIN_JUNK = re.compile(r"[†‡¶¸©®÷¤×Ÿ„‹›Œž¥£¢±º»½¾]")


def detect_encoding(data):
    """Classify a PDF's Bengali encoding before trusting any text from it.

    Two distinct defects exist in Bangladeshi government PDFs and they need
    different fixes. Emitting text without knowing which one you have means
    silently publishing mojibake:

      'nikosh_cmap'  - Unicode Nikosh with a broken ToUnicode CMap and visual
                       ordering. Handled by this module.
      'legacy_bijoy' - ASCII-mapped legacy font (SutonnyMJ/Bijoy). Text comes
                       out as Latin soup: '†iwR÷vW© bs' = 'রেজিস্টার্ড নং'.
                       NOT handled - needs a Bijoy->Unicode mapping table.
      'plain'        - already correct Unicode.
      'empty'        - scanned images, needs OCR.
    """
    # Some gov servers return an HTML error page with Content-Type application/pdf.
    # Reporting that as "empty" (i.e. "a scan needing OCR") sends the caller down
    # the wrong path; it is not a PDF at all. Found by the ingestion agent on
    # admin.ldtax.gov.bd, which served 6,970 bytes ending in "</html>".
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        return "not_a_pdf", 0.0

    from pdfminer.high_level import extract_text as raw_text
    try:
        sample = raw_text(io.BytesIO(data), maxpages=3) or ""
    except Exception:
        return "empty", 0.0
    if len(sample.strip()) < 40:
        return "empty", 0.0
    bn = sum(1 for c in sample if 0x980 <= ord(c) <= 0x9FF)
    junk = len(LATIN_JUNK.findall(sample))
    ratio = bn / max(len(sample), 1)
    if junk > 5 and ratio < 0.05:
        return "legacy_bijoy", ratio
    if ratio < 0.05:
        # Little Bengali AND little real English => some OTHER legacy Bengali
        # font mapping we have no table for. Latin soup like 'qeREq\{rl.' must
        # not be reported as "plain", or callers treat gibberish as valid text.
        # (Found by the ingestion agent on ldtax.gov.bd circulars.)
        toks = re.findall(r"[A-Za-z]{2,}", sample)
        wordish = sum(1 for t in toks if re.search(r"[aeiouAEIOU]", t) and len(t) <= 14)
        if len(toks) >= 20 and wordish / max(len(toks), 1) < 0.55:
            return "legacy_unknown", ratio
        return "plain", ratio
    return ("nikosh_cmap" if corrections_for_pdf(data) else "plain"), ratio


def extract_text(data, pages=None):
    """Extract decoded Bengali text from PDF bytes.

    Patches pdfminer's CID->unicode lookup with the glyph-name corrections,
    then applies visual->logical reordering per text line.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine
    import pdfminer.pdffont as pf

    kind, _ = detect_encoding(data)
    if kind == "legacy_bijoy":
        # Legacy SutonnyMJ: hand off to the Bijoy substitution decoder.
        from pdfminer.high_level import extract_text as _raw
        import bijoy
        raw = _raw(io.BytesIO(data)) or ""
        cov = bijoy.coverage(raw)
        # 0.70, not 0.90: mixed-encoding gazettes decode their PROSE well while
        # leaving numeric columns as "(cid:N)". Refusing the whole document would
        # throw away readable text; the markers stay in-band so the failure is
        # visible. The hard rule lives downstream instead - see has_unmapped().
        if cov < 0.70:
            raise UnsupportedEncoding(
                f"Bijoy table only recognises {cov:.0%} of this document's characters "
                f"(threshold 70%). Refusing rather than returning mostly-mojibake.")
        return [(0, bijoy.decode(l.strip()))
                for l in raw.splitlines() if l.strip()]
    if kind == "not_a_pdf":
        raise UnsupportedEncoding(
            "URL did not return a PDF (body is not %PDF-; the server likely served an "
            "HTML error page with a PDF content-type). Nothing to decode.")
    if kind == "legacy_unknown":
        raise UnsupportedEncoding(
            "PDF uses an unrecognised legacy Bengali font encoding (not Bijoy/SutonnyMJ). "
            "No mapping table exists for it. Refusing rather than returning gibberish.")
    if kind == "empty":
        raise UnsupportedEncoding(
            "PDF has no extractable text layer (scanned). Use tools/ocr.py explicitly - "
            "OCR is deliberately NOT wired in automatically: it is slow, and on these "
            "documents it is unreliable on exactly the dense fee tables that matter, so a "
            "silent fallback would hide that behind plausible-looking output.")

    fixes = corrections_for_pdf(data)
    orig = pf.PDFCIDFont.to_unichr

    def patched(self, cid):
        table = fixes.get(str(getattr(self, "basefont", ""))) or \
                fixes.get("/'%s'" % getattr(self, "basefont", ""))
        if table and cid in table:
            return table[cid]
        return orig(self, cid)

    pf.PDFCIDFont.to_unichr = patched
    try:
        lines = []
        for pno, layout in enumerate(extract_pages(io.BytesIO(data), laparams=LAParams())):
            if pages is not None and pno not in pages:
                continue
            for el in layout:
                if not isinstance(el, LTTextContainer):
                    continue
                for line in el:
                    # A text container yields LTTextLine, but can also yield a
                    # bare LTChar for stray glyphs; only lines are iterable.
                    if not isinstance(line, LTTextLine):
                        continue
                    t = "".join(c.get_text() for c in line if isinstance(c, LTChar))
                    if t.strip():
                        lines.append((pno, reorder(t.rstrip("\n"))))
        return lines
    finally:
        pf.PDFCIDFont.to_unichr = orig


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "tools")
    from fetch_cache import fetch
    url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://nbr.gov.bd/uploads/cconbr/Final_Draft_Citizen_2026.pdf"
    data = fetch(url)["body"]
    print("font corrections:", {k: len(v) for k, v in corrections_for_pdf(data).items()})
    for pno, line in extract_text(data, pages={7}):
        print(f"[p{pno+1}] {line}")
