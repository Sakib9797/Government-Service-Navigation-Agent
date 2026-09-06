"""

Decode legacy Bijoy / SutonnyMJ ASCII-mapped Bengali.


Older Bangladeshi government documents -- gazettes especially -- were typeset
with SutonnyMJ, which maps Bengali glyphs onto Latin-1 code points. Extracted

text looks like Latin soup:


    '†iwR÷vW© bs wW G-1'   ->  'রেজিস্টার্ড নং ডি এ-১'
    'evsjv‡`k †M‡RU'       ->  'বাংলাদেশ গেজেট'

    'MYcÖRvZš¿x'           ->  'গণপ্রজাতন্ত্রী'


This is a substitution cipher plus the same visual->logical reordering Bengali
always needs, so it is decodable deterministically.


The table below was DERIVED FROM AND VALIDATED AGAINST a real document (DNCC's
2016 Bangladesh Gazette on the city-corporation model tax schedule), not

transcribed from memory. Run this module directly to see the validation suite;
`coverage()` reports what fraction of a document's characters the table knows,

so an incomplete decode is visible rather than silent.


Order of operations matters: longest sequences first (conjuncts), then single
characters, then reordering.

"""
import re


# --- conjuncts and multi-character sequences (matched before single chars) ---
CONJ = {

    "Av": "আ", "A¨": "অ্যা", "B©": "ঈ",
    "¯Í": "স্ত", "¯'": "স্থ", "¯^": "স্ব", "¯ú": "স্প", "¯§": "স্ম", "¯‹": "স্ক",

    "š—": "ন্ত", "›`": "ন্দ", " Û": "ণ্ড", "Ð": "ণ্ড", "Ú": "ষ্ট", "÷": "ষ্ট",
    "³": "ক্ত", "¶": "ক্ষ", "Á": "জ্ঞ", "š¿": "ন্ত্র", "š": "ন্ত",

    "ÿ": "ক্ষ", "¡": "্ব", "¢": "্ভ", "Ÿ": "্ব",
    "‡v": "ো", "‡Š": "ৌ", "†v": "ো",

    # further conjuncts observed in the 2016 gazette
    "¤œ": "ম্ন", "¬": "্ল", "œ": "্ন", "½": "ঙ্গ", "ã": "ব্দ", "Ë": "ত্ত",

    "¤": "ম্", "ƒ": "ূ", "ª": "্র", "¯’": "স্থ", "’": "থ", "Ø": "দ্ব",
    "×": "দ্ধ", "¢": "্ভ", "‘": "'", "Ô": "'", "Õ": "'",

    # remaining conjuncts seen in the gazette's business-tax tables
    "ô": "ষ্ঠ", "›": "ন্ট", "Í": "্ত", "¾": "জ্জ", "ó": "ষ্ট", "ˆ": "ৈ",
    # from the 2018 Birth & Death Registration Rules gazette
    "Î": "ত্র", "µ": "ক্র", "¥": "ন্ম", "¤ú": "ম্প",
    # from the 2018 Birth & Death Registration Rules gazette (Rule 9)
    "Ü": "ন্ধ", "ß": "প্ত", "ø": "্ল", "¦": "ব", "^": "ব", "„": "ৃ",
    "‥": "", "Û": "ন্ড",
    "~": "্", "†¯": "সে", "Ò": '"', "Ó": '"',

}


# --- single characters ---
SINGLE = {

    # independent vowels
    "A": "অ", "B": "ই", "C": "ঈ", "D": "উ", "E": "ঊ", "F": "ঋ",

    "G": "এ", "H": "ঐ", "I": "ও", "J": "ঔ",
    # consonants

    "K": "ক", "L": "খ", "M": "গ", "N": "ঘ", "O": "ঙ",
    "P": "চ", "Q": "ছ", "R": "জ", "S": "ঝ", "T": "ঞ",

    "U": "ট", "V": "ঠ", "W": "ড", "X": "ঢ", "Y": "ণ",
    "Z": "ত", "_": "থ", "`": "দ", "a": "ধ", "b": "ন",

    "c": "প", "d": "ফ", "e": "ব", "f": "ভ", "g": "ম",
    "h": "য", "i": "র", "j": "ল", "k": "শ", "l": "ষ", "m": "স", "n": "হ",

    "o": "ড়", "p": "ঢ়", "q": "য়", "r": "ৎ",
    "'": "থ", "¯": "স্",

    # vowel signs
    "v": "া", "w": "ি", "x": "ী", "y": "ু", "z": "ূ", "…": "ৃ",

    "‡": "ে", "†": "ে", "ˆ": "ৈ", "Š": "ৌ",
    # marks

    "s": "ং", "t": "ঃ", "u": "ঁ", "š": "ন্ত",
    "©": "র্",       # reph (র্) - repositioned below

    "Ö": "্র",       # ra-phala (্র)
    "¿": "্র",

    "¨": "্য",       # ya-phala (্য)
    "&": "্",             # hasant

    "­": "্",
    "|": "।", "Ñ": "-", "―": "-", "‒": "-",

}
DIGITS = {str(i): "০১২৩৪৫৬৭৮৯"[i] for i in range(10)}


PRE_BASE = "িেৈ"
CONSONANT = re.compile(r"[ক-হৎড়-য়]")   # explicit escapes: a literal ড় may be stored decomposed, which breaks the range

VIRAMA = "্"
REPH = "র্"


# ASCII that should survive decoding untouched (punctuation, whitespace).
PASSTHROUGH = " \t\n\r.,:;()[]/%-–—\"'"
_KEYS = sorted(set(CONJ) | set(SINGLE) | set(DIGITS), key=len, reverse=True)


# pdfminer emits "(cid:NN)" for a glyph it cannot map at all. Those must be
# protected before substitution: otherwise the decoder transliterates the

# diagnostic itself (c->প, i->র, d->ফ) and "(cid:18)" becomes "(পরফ:১৮)",
# hiding a real extraction failure AND inflating the coverage score.

CID = re.compile(r"\(cid:(\d+)\)")


def _substitute(s):
    """Substitute Bijoy code points, protecting unmapped-glyph markers.
    Sentinels use the Unicode Private Use Area: they cannot collide with any
    table entry, and unlike a digit-bearing marker they survive substitution
    (an "@@CID0@@" sentinel would come back as "@@CID০@@" once digits are
    Bengali-ised, and the restore would silently drop it).
    """
    cids = []
    def _stash(m):
        cids.append(m.group(0))
        return chr(0xE000 + len(cids) - 1)
    s = CID.sub(_stash, s)
    out, i, unknown = [], 0, 0
    while i < len(s):
        for k in _KEYS:
            if s.startswith(k, i):
                out.append(CONJ[k] if k in CONJ else (SINGLE[k] if k in SINGLE else DIGITS[k]))
                i += len(k)
                break
        else:
            ch = s[i]
            if 0xE000 <= ord(ch) <= 0xF8FF:          # protected sentinel
                out.append(ch)
            elif ch.isspace() or (ch.isascii() and (ch.isalnum() or ch in PASSTHROUGH)):
                out.append(ch)
            else:
                unknown += 1
                out.append(ch)
            i += 1
    res = "".join(out)
    for k, rawmark in enumerate(cids):
        res = res.replace(chr(0xE000 + k), rawmark)
    return res, unknown + len(cids)


def coverage(s):
    """Fraction of glyphs successfully decoded.
    An unmapped "(cid:NN)" counts as ONE failure, not as five happily decoded
    ASCII characters - otherwise a document that is mostly extraction failures
    scores near-perfect. This correction moved the DNCC gazette from an
    apparent 98% to a real 47%.
    """
    protected = CID.sub("", s)
    _, unknown = _substitute(s)
    total = sum(1 for c in protected if not c.isspace())
    return 1.0 - (unknown / max(total, 1))


def _reorder(s):
    """Move pre-base vowel signs after their cluster, and reph before it."""

    out, i, n = [], 0, len(s)
    while i < n:

        ch = s[i]
        if ch in PRE_BASE:

            j = i + 1
            if j < n and CONSONANT.match(s[j]):

                j += 1
                while j + 1 < n and s[j] == VIRAMA and CONSONANT.match(s[j + 1]):

                    j += 2
                out.append(s[i + 1:j])

                out.append(ch)
                i = j

                continue
        out.append(ch)

        i += 1
    t = "".join(out)


    # reph: typed AFTER the consonant (+ its vowel sign) it sits on; logically precedes it.
    def fix(m):

        return REPH + m.group(1) + m.group(2)
    return re.sub(r"([ক-হৎড়-য়](?:্[ক-হৎড়-য়])*)([া-ৌ]*)" + REPH, fix, t)


def decode(s):
    txt, _ = _substitute(s)

    return _reorder(txt)



def coverage(s):
    """Fraction of glyphs successfully decoded.

    An unmapped "(cid:NN)" counts as ONE failure, not as five happily decoded
    ASCII characters - otherwise a document that is mostly extraction failures
    scores near-perfect. This correction moved the DNCC gazette from an
    apparent 98% to a real 87%.
    """
    protected = CID.sub("", s)
    _, unknown = _substitute(s)
    total = sum(1 for c in protected if not c.isspace())
    return 1.0 - (unknown / max(total, 1))


# Alignment pairs taken from DNCC's 2016 Bangladesh Gazette. These are the
# ground truth the table was built against; they run on import-as-main.
CASES = [
    ("evsjv‡`k", "বাংলাদেশ"),
    ("†M‡RU", "গেজেট"),
    ("miKvi", "সরকার"),
    ("MYcÖRvZš¿x", "গণপ্রজাতন্ত্রী"),
    ("cÖÁvcb", "প্রজ্ঞাপন"),
    ("AwZwi³", "অতিরিক্ত"),
    ("msL¨v", "সংখ্যা"),
    ("Rvbyqvwi", "জানুয়ারি"),
    ("iweevi", "রবিবার"),
    ("KZ…©c¶", "কর্তৃপক্ষ"),
]

if __name__ == "__main__":
    import unicodedata
    ok = 0
    print(f"{'input':<16}{'decoded':<20}{'expected':<20}")
    print("-" * 58)
    for src, want in CASES:
        got = unicodedata.normalize("NFC", decode(src))
        want_n = unicodedata.normalize("NFC", want)
        mark = "ok " if got == want_n else "FAIL"
        ok += got == want_n
        print(f"{mark} {src:<14}{got:<20}{want_n:<20}")
    print(f"\n{ok}/{len(CASES)} alignment cases pass")
