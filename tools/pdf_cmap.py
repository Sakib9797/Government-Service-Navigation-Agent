"""
Parse a PDF ToUnicode CMap, and recover the correct mapping from the embedded
font's glyph names.

Why this exists: Bangladeshi government PDFs (Nikosh font, produced by Word)
ship a ToUnicode CMap that yields mojibake -- 'তবনামূদল্য' where the rendered
page reads 'বিনামূল্যে'. The embedded font subset, however, names its glyphs
uniXXXX, which is the correct Unicode. So the glyph names are recoverable
ground truth and the CMap is the broken part.

CMap syntax handled:
    beginbfchar   <src> <dst>                       endbfchar
    beginbfrange  <lo> <hi> <dst>                   endbfrange
    beginbfrange  <lo> <hi> [ <d0> <d1> ... ]       endbfrange   <- the array form
The array form is why a naive three-<hex> regex breaks: it slides across
entries and produces nonsense codepoints.
"""
import re

TOKEN = re.compile(r"<([0-9A-Fa-f]+)>|(\[)|(\])|(\S+)")


def _hex2str(h):
    if len(h) % 4:
        h = h.zfill(len(h) + (4 - len(h) % 4))
    return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4)
                   if int(h[i:i + 4], 16) < 0x110000)


def parse_tounicode(data):
    """Return {cid: unicode_string} from a ToUnicode CMap stream."""
    if isinstance(data, bytes):
        data = data.decode("latin-1", errors="replace")
    out = {}

    for blk in re.findall(r"beginbfchar(.*?)endbfchar", data, re.S):
        pairs = re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk)
        for src, dst in pairs:
            if dst:
                out[int(src, 16)] = _hex2str(dst)

    for blk in re.findall(r"beginbfrange(.*?)endbfrange", data, re.S):
        toks = [t for t in TOKEN.findall(blk)]
        i = 0
        while i < len(toks):
            if not toks[i][0]:
                i += 1
                continue
            lo = int(toks[i][0], 16)
            if i + 1 >= len(toks) or not toks[i + 1][0]:
                i += 1
                continue
            hi = int(toks[i + 1][0], 16)
            j = i + 2
            if j < len(toks) and toks[j][1] == "[":          # array form
                j += 1
                cid = lo
                while j < len(toks) and toks[j][2] != "]":
                    if toks[j][0]:
                        out[cid] = _hex2str(toks[j][0])
                        cid += 1
                    j += 1
                i = j + 1
            elif j < len(toks) and toks[j][0]:                # single dst form
                base = _hex2str(toks[j][0])
                if base and hi >= lo and hi - lo < 65536:
                    for k in range(hi - lo + 1):
                        last = ord(base[-1]) + k
                        if last < 0x110000:
                            out[lo + k] = base[:-1] + chr(last)
                i = j + 1
            else:
                i += 1
    return out


GLYPHNAME = re.compile(r"^uni([0-9A-Fa-f]{4})$")


def glyphname_map(ttfont):
    """Return {gid: unicode_string} from the font's own glyph names."""
    out = {}
    for gid, name in enumerate(ttfont.getGlyphOrder()):
        m = GLYPHNAME.match(name or "")
        if m:
            out[gid] = chr(int(m.group(1), 16))
    return out


def font_unicode_map(ttfont, max_rounds=6):
    """Best-effort {glyph_name: unicode_string} recovered from the font itself.

    Three sources, in increasing order of cleverness:

      1. Glyph NAMES of the form uniXXXX.
      2. The font's own cmap (unicode -> glyph name), inverted.
      3. GSUB closure. Subset fonts name most glyphs 'glyphNNNNN', so 1 and 2
         miss them - but GSUB records how each was derived. Nikosh generates
         contextual width variants of the pre-base vowel signs, e.g.
             SingleSubst uni09C7 -> glyph00495
         so glyph00495 IS ে, even though the PDF's ToUnicode calls it 'ব'.
         Ligature substitutions map a component sequence to one glyph, so the
         output inherits the concatenation of its components.

    Iterated to a fixpoint because substitutions chain.
    """
    out = {}
    for name in ttfont.getGlyphOrder():
        m = GLYPHNAME.match(name or "")
        if m:
            out[name] = chr(int(m.group(1), 16))
    try:
        for uni, gname in ttfont.getBestCmap().items():
            out.setdefault(gname, chr(uni))
    except Exception:
        pass

    if "GSUB" not in ttfont:
        return out
    lookups = getattr(ttfont["GSUB"].table.LookupList, "Lookup", []) or []
    for _ in range(max_rounds):
        grew = False
        for lk in lookups:
            for st in getattr(lk, "SubTable", []) or []:
                if lk.LookupType == 1 and getattr(st, "mapping", None):
                    for src, dst in st.mapping.items():
                        if src in out and dst not in out:
                            out[dst] = out[src]
                            grew = True
                elif lk.LookupType == 4 and getattr(st, "ligatures", None):
                    for first, ligs in st.ligatures.items():
                        for lig in ligs:
                            comps = [first] + list(lig.Component)
                            if all(c in out for c in comps) and lig.LigGlyph not in out:
                                out[lig.LigGlyph] = "".join(out[c] for c in comps)
                                grew = True
        if not grew:
            break
    return out
