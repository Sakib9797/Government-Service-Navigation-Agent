"""Agent 3: judge staleness on the CONTENT date, not the fetch date.

explain.md's schema only had last_scraped_date. Step 2 found the passport fee
page self-reporting 2020-01-20 while a scrape today would stamp 2026-09-04 --
so a record can look fresh while its numbers are six years old. This agent keys
on source_last_updated and degrades to a louder warning when that is missing.
"""
from datetime import date

STALE_DAYS = 90


def _age(iso):
    if not iso:
        return None
    y, m, d = (int(x) for x in iso.split("-"))
    return (date.today() - date(y, m, d)).days


BN_D = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def _fmt_age_bn(days):
    if days < 365:
        return f"{str(days).translate(BN_D)} দিন আগে"
    y, d = divmod(days, 365)
    return f"প্রায় {str(y).translate(BN_D)} বছর, {str(d).translate(BN_D)} দিন আগে"


def _fmt_age(days):
    """Proportionate wording. '0 year(s) ago' for a 5-month-old page reads as
    noise and trains users to ignore the warning that matters - the 6-year-old
    passport fee page."""
    if days < 365:
        return f"{days} days ago"
    y, d = divmod(days, 365)
    return f"about {y} year{'s' if y > 1 else ''}, {d} days ago"


def assess(record):
    if record is None:
        return {"level": "none", "age_days": None, "notes": [], "notes_bn": []}

    notes, notes_bn, level = [], [], "fresh"
    age = _age(record.get("source_last_updated"))

    if age is None:
        level = "unknown"
        notes.append("The source does not publish a last-updated date, so its age cannot be verified.")
        notes_bn.append("উৎসটি হালনাগাদের তারিখ প্রকাশ করে না, তাই এর বয়স যাচাই করা যাচ্ছে না।")
    elif age > STALE_DAYS:
        level = "stale"
        notes.append(f"The source page was last updated {record['source_last_updated']} "
                     f"({_fmt_age(age)}).")
        notes_bn.append(f"উৎস পাতাটি সর্বশেষ হালনাগাদ হয়েছে {record['source_last_updated']} "
                        f"({_fmt_age_bn(age)})।")

    # Per-fee ages: a fee schedule and a document list age independently.
    worst = None
    for f in record.get("fees", []):
        fa = _age(f.get("source_last_updated"))
        if fa is not None and fa > STALE_DAYS and (worst is None or fa > worst[0]):
            worst = (fa, f.get("source_last_updated"))
    if worst:
        level = "stale"
        sev = "and may well be out of date" if worst[0] > 365 else "so confirm before you pay"
        sev_bn = "এবং তা পুরোনো হয়ে থাকতে পারে" if worst[0] > 365 else "তাই টাকা দেওয়ার আগে নিশ্চিত হয়ে নিন"
        notes.append(f"Fee figures come from a page last updated {worst[1]} "
                     f"({_fmt_age(worst[0])}) {sev}.")
        notes_bn.append(f"ফি-এর তথ্য এসেছে এমন একটি পাতা থেকে যা সর্বশেষ হালনাগাদ হয়েছে {worst[1]} "
                        f"({_fmt_age_bn(worst[0])}) {sev_bn}।")

    if record["verification"]["status"] == "unverified":
        level = "unverified"
        notes.append("This service could not be verified against an official source.")
        notes_bn.append("এই সেবাটি কোনো সরকারি উৎসের বিপরীতে যাচাই করা যায়নি।")

    return {"level": level, "age_days": age, "notes": notes, "notes_bn": notes_bn}
