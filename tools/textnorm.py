"""
Unicode normalisation for Bengali text. Apply at EVERY text boundary.

Bangladeshi government pages emit the precomposed forms য় (U+09DF), ড় (U+09DC)
and ঢ় (U+09DD). These are Unicode composition exclusions, so NFC represents
them decomposed as base + nukta (U+09AF U+09BC, etc.). A user typing on a
different keyboard/IME produces the other form.

The two forms are visually identical and compare UNEQUAL. Untreated, this
silently breaks alias matching, document lookup and any exact comparison -
found by eval question p02, where 'জাতীয় পরিচয়পত্র' failed to match the same
string in the record.
"""
import unicodedata


def nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def deep(obj):
    """Normalise every string in a nested structure."""
    if isinstance(obj, str):
        return nfc(obj)
    if isinstance(obj, list):
        return [deep(x) for x in obj]
    if isinstance(obj, dict):
        return {nfc(k): deep(v) for k, v in obj.items()}
    return obj
