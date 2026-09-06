"""
Agent 5: assemble the final answer.

Deliberately TEMPLATE-BASED, not LLM-generated. Every factual line here is
copied from a verified record or the curated scam table; nothing is phrased by
a model that could drift a number or invent a document. explain.md 5.1 forbids
the LLM generating fees, document lists or scam warnings from its own
knowledge - the simplest way to guarantee that is to not give a model the pen.

Rules enforced here:
  * Fees are read from record["fees"], never from a retrieved chunk.
  * A fee with amount_bdt = None renders as "not verified", never omitted and
    never guessed.
  * Every fee and every scam entry prints its source URL and source date.
  * A stale or unverified record prints the warning ABOVE the facts, not below.

LLM SEAM: a model may later rephrase this into warmer Bengali, but it must be
given the composed facts and forbidden to add or alter any number, document or
warning. Facts first, phrasing second - never the reverse.
"""

import sys
sys.path.insert(0, "tools")
from lang import detect, pick

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

# Every user-visible string, in both languages. The citizen gets the whole reply
# in the language they asked in - not an English shell around Bengali content.
LABELS = {
    "no_match":     {"en": "I could not identify this service confidently",
                     "bn": "আপনি কোন সেবার কথা বলছেন তা আমি নিশ্চিতভাবে বুঝতে পারিনি"},
    "only_verified": {"en": "I only answer about services I have verified against an official source, "
                            "so I would rather say I don't know than send you to the wrong office.",
                      "bn": "আমি কেবল সেই সেবাগুলো নিয়েই উত্তর দিই যেগুলো সরকারি উৎস থেকে যাচাই করা হয়েছে। "
                            "ভুল অফিসে পাঠানোর চেয়ে 'জানি না' বলা ভালো।"},
    "covered":      {"en": "Currently covered:", "bn": "বর্তমানে যেসব সেবা রয়েছে:"},
    "covered_list": {"en": "passport, birth registration, death registration, e-TIN, income tax return, "
                           "driving licence, vehicle registration, land records (khatian).",
                     "bn": "পাসপোর্ট, জন্ম নিবন্ধন, মৃত্যু নিবন্ধন, ই-টিআইএন, আয়কর রিটার্ন, "
                           "ড্রাইভিং লাইসেন্স, যানবাহন রেজিস্ট্রেশন, জমির খতিয়ান।"},
    "elsewhere":    {"en": "For anything else, the government's own service directory is "
                           "<https://bangladesh.gov.bd> and the national helpline is **333**.",
                     "bn": "অন্য যেকোনো সেবার জন্য সরকারের নিজস্ব সেবা তালিকা "
                           "<https://bangladesh.gov.bd> এবং জাতীয় হেল্পলাইন **৩৩৩**।"},
    "office":       {"en": "Office:", "bn": "দপ্তর:"},
    "verify_first": {"en": "Verify before you act.", "bn": "কাজ করার আগে যাচাই করে নিন।"},
    "confirm_source": {"en": "Always confirm at the source:", "bn": "সবসময় মূল উৎসে যাচাই করুন:"},
    "no_verified":  {"en": "I do not have verified details for this service.",
                     "bn": "এই সেবার যাচাইকৃত তথ্য আমার কাছে নেই।"},
    "no_guess":     {"en": "I am not going to guess at documents or fees, because a wrong answer "
                           "here costs you money or a wasted trip.",
                     "bn": "আমি অনুমান করে কাগজপত্র বা ফি বলব না, কারণ ভুল তথ্যের জন্য আপনার "
                           "টাকা নষ্ট হতে পারে বা অযথা যাতায়াত করতে হতে পারে।"},
    "where_check":  {"en": "Where to check:", "bn": "কোথায় যাচাই করবেন:"},
    "answer":       {"en": "Answer", "bn": "উত্তর"},
    "full_record":  {"en": "Full verified record for this service",
                     "bn": "এই সেবার সম্পূর্ণ যাচাইকৃত তথ্য"},
    "documents":    {"en": "Required documents", "bn": "প্রয়োজনীয় কাগজপত্র"},
    "docs_missing": {"en": "Not available from a verified source yet — please confirm with the office.",
                     "bn": "যাচাইকৃত উৎসে এখনো পাওয়া যায়নি — অনুগ্রহ করে অফিসে নিশ্চিত করে নিন।"},
    "process":      {"en": "Process", "bn": "আবেদনের ধাপ"},
    "where":        {"en": "Where:", "bn": "কোথায়:"},
    "fees":         {"en": "Fees", "bn": "ফি"},
    "col_service":  {"en": "Service", "bn": "সেবা"},
    "col_fee":      {"en": "Fee (BDT)", "bn": "ফি (টাকা)"},
    "col_updated":  {"en": "Source last updated", "bn": "উৎস হালনাগাদ"},
    "fee_unverified": {"en": "not verified — ask the office",
                       "bn": "যাচাই করা হয়নি — অফিসে জিজ্ঞাসা করুন"},
    "fee_free":     {"en": "free (বিনামূল্যে)", "bn": "বিনামূল্যে"},
    "protect":      {"en": "Know this before anyone offers to 'help'",
                     "bn": "কেউ 'সাহায্য' করতে চাইলে এটি জেনে রাখুন"},
    "source":       {"en": "Source:", "bn": "উৎস:"},
    "caveat":       {"en": "Caveat:", "bn": "সতর্কতা:"},
    "src_updated":  {"en": "Source last updated:", "bn": "উৎস সর্বশেষ হালনাগাদ:"},
    "checked":      {"en": "Checked by this tool:", "bn": "এই টুল যাচাই করেছে:"},
    "apply_at":     {"en": "Apply at:", "bn": "আবেদন করুন:"},
    "contact":      {"en": "Contact:", "bn": "যোগাযোগ:"},
    "unknown":      {"en": "unknown", "bn": "অজানা"},
}


def _bn(n):
    return f"{n:,}".translate(BN_DIGITS)


def compose(query, intent, retrieved, freshness, scams, lang=None):
    rec = retrieved.get("record")
    cat = intent["category"]
    # Answer in the language the citizen asked in. Bengali script and romanised
    # Banglish both get Bengali; see tools/lang.py for why Banglish counts as
    # Bengali rather than English.
    lang = lang or detect(query)
    t = lambda k: pick(LABELS[k], lang)
    L = []

    # ---- no match: say so, do not improvise ----
    if cat == "unknown_service" or rec is None:
        L.append(f"## {t('no_match')}\n")
        L.append(f"_{intent['rationale']}_\n")
        L.append(t("only_verified") + "\n")
        L.append(f"**{t('covered')}** {t('covered_list')}\n")
        L.append(t("elsewhere"))
        return "\n".join(L)

    L.append(f"## {rec['service_name_bn']}")
    L.append(f"**{rec['service_name_en']}**")
    L.append(f"**{t('office')}** {rec['office']}\n")

    # ---- warnings go FIRST, so they cannot be missed under a table of numbers ----
    if freshness["level"] in ("stale", "unknown", "unverified"):
        L.append(f"> ⚠️ **{t('verify_first')}**")
        fnotes = (freshness.get("notes_bn") if lang == "bn" else None) or freshness["notes"]
        for n in fnotes:
            L.append(f"> - {n}")
        L.append(f"> - {t('confirm_source')} <{rec['source_url']}>\n")

    if rec["verification"]["status"] == "unverified":
        L.append(f"**{t('no_verified')}** {t('no_guess')}\n")
        for n in rec.get("notes", [])[:2]:
            L.append(f"- {n}")
        L.append(f"\n**{t('where_check')}** <{rec['source_url']}>")
        if rec.get("contact"):
            L.append(f"**{t('contact')}** {rec['contact']}")
        return "\n".join(L)

    # ---- targeted answer from the LLM, if one is configured ----
    # This is the only generated text in the reply. It leads, because it answers
    # the question actually asked; the verified record still follows underneath
    # in full, so nothing is hidden and the fee table stays template-rendered.
    # Any failure (no key, API error, a number not present in the FACTS) falls
    # through silently to the template-only answer below.
    try:
        from agents.llm_composer import compose_llm
        led, why = compose_llm(query, rec, retrieved.get("chunks") or [], freshness, scams)
    except Exception:
        led, why = None, "llm_composer unavailable"
    if led:
        L.append(f"### ✅ {t('answer')}")
        L.append(led)
        L.append("")
        L.append(f"<details><summary>📋 {t('full_record')}</summary>")
        L.append("")

    # ---- documents ----
    docs = [d for v in rec.get("variants", []) for d in v.get("required_docs", [])]
    L.append(f"### 📄 {t('documents')}")
    if docs:
        for d in docs:
            L.append(f"- {d['doc']}")
        L.append("")
    else:
        L.append(f"_{t('docs_missing')}_\n")

    # ---- steps ----
    steps = [s for v in rec.get("variants", []) for s in v.get("steps", [])]
    if steps:
        L.append(f"### 🪜 {t('process')}")
        for i, s in enumerate(steps, 1):
            where = f"  \n  _{t('where')}_ {s['where']}" if s.get("where") else ""
            L.append(f"{i}. {s['step']}{where}")
        L.append("")

    # ---- fees: read straight from the record's keyed lookup ----
    if rec.get("fees"):
        L.append(f"### 💰 {t('fees')}")
        L.append(f"| {t('col_service')} | {t('col_fee')} | {t('col_updated')} |")
        L.append("|---|---|---|")
        for f in rec["fees"]:
            if lang == "bn":
                label = f.get("label_bn") or f.get("label_en") or f["fee_key"]
            else:
                label = f.get("label_en") or f.get("label_bn") or f["fee_key"]
            if f["amount_bdt"] is None:
                amount = f"**{t('fee_unverified')}**"
            elif f["amount_bdt"] == 0:
                amount = f"**{t('fee_free')}**"
            else:
                amount = f"{_bn(f['amount_bdt'])} / {f['amount_bdt']:,}"
            L.append(f"| {label} | {amount} | {f.get('source_last_updated') or t('unknown')} |")
        L.append("")

    # ---- curated scam guidance ----
    if scams:
        L.append(f"### 🛡️ {t('protect')}")
        for s in scams:
            claim = (s.get("claim_bn") if lang == "bn" else None) or s["claim_en"]
            L.append(f"- **{claim}**")
            if s.get("why_it_matters_en"):
                L.append(f"  {s['why_it_matters_en']}")
            src = s.get("source_document") or s["source_url"]
            L.append(f"  _{t('source')} <{src}> ({s['source_date']})_")
            if s.get("caveat"):
                L.append(f"  _{t('caveat')} {s['caveat']}_")
        L.append("")

    # ---- provenance, always ----
    L.append("---")
    L.append(f"**{t('source')}** <{rec['source_url']}>")
    L.append(f"**{t('src_updated')}** {rec.get('source_last_updated') or t('unknown')}  ·  "
             f"**{t('checked')}** {rec['last_scraped_date']}")
    if rec.get("apply_portal"):
        L.append(f"**{t('apply_at')}** <{rec['apply_portal']}>")
    if rec.get("contact"):
        L.append(f"**{t('contact')}** {rec['contact']}")
    if led:
        L.append("")
        L.append("</details>")
    return "\n".join(L)
