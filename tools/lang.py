"""
Detect the language a citizen asked in, so the answer comes back in the same one.

Three input forms occur in practice (explain.md 5.4):

    Bengali script   "জন্ম নিবন্ধন করতে কত টাকা লাগে?"
    English          "how much does birth registration cost"
    Banglish         "jonmo nibondhon korte koto taka lage"   <- Bengali in Latin letters

Banglish is treated as BENGALI. Someone writing "jonmo nibondhon korte koto taka
lage" is asking in Bengali; they are typing in Latin because of the keyboard on
their phone, not because they want an English reply. Flip BANGLISH_REPLIES_IN to
"en" if you would rather mirror the script than the language.

Detection is deliberately simple and dependency-free: script first, then a
closed list of high-frequency Banglish function words. It never guesses from a
single ambiguous token.
"""
import re

BANGLISH_REPLIES_IN = "bn"

BENGALI_SCRIPT = re.compile(r"[ঀ-৿]")

# High-frequency Bengali function/question words as people romanise them.
# Function words, not service nouns: "passport" and "TIN" are used in English
# sentences too, so they carry no signal.
BANGLISH = {
    "koto", "koto", "kivabe", "kibhabe", "ki", "kise", "kothay", "kothae", "kobe", "keno",
    "lage", "lagbe", "lage", "korte", "korbo", "korte", "kora", "korar", "kore",
    "ami", "amar", "amake", "amader", "apni", "apnar", "tar", "tara",
    "taka", "tk", "hobe", "hoy", "hoyni", "hoye", "geche", "gele", "chai", "chaile",
    "dorkar", "proyojon", "nite", "pabo", "paoa", "jabo", "jete", "ache", "nei",
    "jonno", "jonne", "ekta", "akta", "kono", "shob", "kaj", "din", "bochor", "bochhor",
    "bhul", "thik", "kagoj", "kagojpotro", "sonod", "nibondhon", "khulte", "tulte",
}
WORD = re.compile(r"[a-z]+")


def detect(text):
    """Return 'bn' or 'en'."""
    if not text or not text.strip():
        return "en"
    if BENGALI_SCRIPT.search(text):
        return "bn"

    words = WORD.findall(text.lower())
    if not words:
        return "en"
    hits = sum(1 for w in words if w in BANGLISH)
    # Two markers, or one in a short query, is enough. A single marker inside a
    # long English sentence ("what documents do I need") is not.
    if hits >= 2 or (hits == 1 and len(words) <= 4):
        return BANGLISH_REPLIES_IN
    return "en"


def pick(labels, lang):
    """labels is {'en': ..., 'bn': ...}; fall back to English."""
    return labels.get(lang) or labels["en"]
