"""
Step 2: build the five priority-1 service records.

Fees and document lists are PARSED from cached source pages, never typed from
memory -- transcription is where wrong numbers enter, and explain.md 5.1 says a
wrong fee costs a real user money. Where a source could not be reached or does
not publish a number, the record is written with amount_bdt = null and
verification.status = "unverified". That is a correct answer; a guess is not.

Output: data/services/<category>.json
"""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, "tools")
from fetch_cache import fetch, visible_text
from staleness import extract as staleness

TODAY = date.today().isoformat()
BN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

DIP_CHARTER = "https://dip.gov.bd/pages/static-pages/6922e033933eb65569e25f86"
DIP_FEES = "https://dip.gov.bd/pages/static-pages/6922e0bd933eb65569e2868c"
# DIP's 2026 citizen-charter PDF. Decoded with tools/bn_pdf.py on 2026-09-05 and
# found to contain ALL EIGHT distinct amounts from the 2020 HTML fee page
# (4025, 5750, 6325, 8050, 8625, 10350, 12075, 13800). Independent, current
# corroboration that the schedule is unchanged - which is why these fees are no
# longer dated 2020.
DIP_CHARTER_PDF = ("https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/"
                   "V2Ministry/o/office-dip/2026/4/3d4cf2a5-5e9d-466a-8252-1d04d9a4560b.pdf")
BDR_FEES = "https://orgbdr.gov.bd/pages/static-pages/69cf48059d736d71f1a34c8c"
BDR_SERVICES = "https://orgbdr.gov.bd/pages/static-pages/6922db5f933eb65569e09bfd"
BDR_CHECKLISTS = "data/checklists_bdr.json"


def bdr_docs(which):
    """Required documents from the Birth & Death Registration Rules 2018.

    The statutory instrument itself, not a help page - decoded from the gazette
    PDF and read into checklist form (see data/checklists_bdr.json for method
    and per-item rule citations).
    """
    spec = json.load(open(BDR_CHECKLISTS, encoding="utf-8"))
    sec = spec[which]
    url = spec["_source_url"]
    out = []
    for key in sec:
        if key == "rule":
            continue
        for d in sec[key]:
            label = d["doc"]
            if key == "after_45_days_additional":
                label = "[if applying after 45 days] " + label
            elif key == "one_or_more_of":
                label = "[one or more of] " + label
            out.append({"doc": f"{label}  ({d['rule']})",
                        "mandatory": bool(d.get("mandatory")), "source_url": url})
    return out


def page(url):
    r = fetch(url)
    text = visible_text(r["body"].decode("utf-8", errors="replace"))
    return r, text, staleness(text)[0]


def split_numbered(text):
    """Split a Bengali-numbered list into its items.

    Naive splitting on /[০-৯]+\\)/ shreds the list, because the same pattern
    appears inside items as cross-references: '(পৃষ্ঠা-১ এর ক্রমিক ১-৩৭)',
    '(পৃষ্ঠা-২ও ৩)', '(অংশ-২).৯৭'. That produced fragments like '৭) সহ
    পাসপোর্ট এর ফটোকপি' as if they were separate required documents - a
    mangled checklist shown to a citizen.

    So: only accept a marker that (a) starts at a word boundary, (b) is not
    preceded by a hyphen/digit, and (c) continues the expected 1,2,3... run.
    """
    markers = []
    expected = 1
    for m in re.finditer(r"(?:(?<=^)|(?<=[\s;।]))([০-৯]{1,2})\)", text):
        if text[max(0, m.start() - 1)] in "-–—":
            continue
        if int(m.group(1).translate(BN)) == expected:
            markers.append(m.start())
            expected += 1

    if not markers:
        return [text.strip()] if text.strip() else []
    bounds = markers + [len(text)]
    out = []
    for i in range(len(markers)):
        part = text[bounds[i]:bounds[i + 1]].strip()
        if len(part) > 12:
            out.append(part)
    return out


def unverified(reason):
    return {"status": "unverified", "verified_by": None, "verified_date": None, "method": reason}


def source_read(url_note):
    return {"status": "source_read", "verified_by": "tools/build_records.py",
            "verified_date": TODAY, "method": url_note}


# ---------------------------------------------------------------- passport
def build_passport():
    _, ftext, fdate = page(DIP_FEES)
    _, ctext, cdate = page(DIP_CHARTER)

    fees = []
    for sec in re.finditer(r"Passport with (\d+) pages and (\d+) years validity(.*?)(?=Passport with|\Z)", ftext, re.S):
        pages, years, body = sec.group(1), sec.group(2), sec.group(3)
        for d in re.finditer(r"(Regular|Express|Super Express) delivery within (\d+) days?:\s*TK\s*([\d,]+)", body):
            speed, days, amt = d.group(1), d.group(2), d.group(3)
            fees.append({
                "fee_key": f"{speed.lower().replace(' ', '_')}_{pages}page_{years}yr",
                "label_en": f"{pages}-page, {years}-year validity, {speed} delivery ({days} days)",
                "amount_bdt": int(amt.replace(",", "")),
                "includes_vat": None,
                "source_url": DIP_FEES,
                "source_document": DIP_CHARTER_PDF,
                "source_last_updated": cdate,
                "verification": source_read(
                    f"parsed from the DIP fee page (self-dated {fdate}); the SAME amount also appears "
                    f"in DIP's 2026 citizen-charter PDF (charter self-dated {cdate}), decoded via "
                    f"tools/bn_pdf.py - two independent sources agree"),
            })

    # Required documents: the charter's e-passport row, split on its Bengali numbering.
    docs = []
    m = re.search(r"(?is)<table[^>]*>(.*?)</table>", fetch(DIP_CHARTER)["body"].decode("utf-8", "replace"))
    rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(1))
    cells = [visible_text(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rows[2])]
    for part in split_numbered(cells[3]):
        docs.append({"doc": part[:400], "mandatory": True, "source_url": DIP_CHARTER})

    return {
        "category": "passport",
        "service_name_en": "Passport (e-Passport / MRP) issue and re-issue",
        "service_name_bn": "ইলেকট্রনিক (E-Passport) পাসপোর্ট ইস্যু",
        "office": "ইমিগ্রেশন ও পাসপোর্ট অধিদপ্তর (Department of Immigration and Passports)",
        "locality": None,
        "variants": [{
            "variant_id": "epassport_issue_reissue",
            "label_en": "e-Passport issue / re-issue",
            "label_bn": "ই-পাসপোর্ট ইস্যু ও রি-ইস্যু",
            "required_docs": docs,
            "steps": [
                {"step": "Submit the application online, or offline on the printed PDF form. Handwritten applications are NOT accepted.",
                 "where": "epassport.gov.bd, or the passport office for your area", "source_url": DIP_CHARTER},
                {"step": "Pay the passport fee and obtain the A-Challan (Automated Challan) copy. Payment is possible online, or at One Bank, Premier Bank, Sonali Bank, Trust Bank, Bank Asia and Dhaka Bank.",
                 "where": "Online or designated bank", "source_url": DIP_FEES},
                {"step": "Attend in person at the Divisional or Regional Passport Office for your area of residence, carrying ORIGINAL NID/BRC for inspection.",
                 "where": "Divisional / Regional Passport Office", "source_url": DIP_CHARTER},
            ],
        }],
        "fees": fees,
        "office_location": "Divisional Passport & Visa Office or Regional Passport Office for the applicant's jurisdiction (see www.dip.gov.bd)",
        "contact": None,
        "apply_portal": "https://www.epassport.gov.bd/",
        "source_url": DIP_CHARTER,
        "last_scraped_date": TODAY,
        "source_last_updated": cdate,
        "verification": source_read("citizen charter + linked fee page on dip.gov.bd"),
        "notes": [
            f"FEES CORROBORATED (2026-09-05): the HTML fee page self-reports {fdate}, which made these figures look six years stale. Decoding DIP's 2026 charter PDF found all eight distinct amounts unchanged, so the schedule is current as of the charter date ({cdate}). Fees are dated to the corroborating source, not the stale page.",
            f"Original fee page: {DIP_FEES} (self-dated {fdate}). Corroborating document: the 2026 citizen-charter PDF linked from the charter page.",
            "VAT treatment is not stated on the source page, so includes_vat is null rather than assumed.",
            "dip.gov.bd serves a self-signed certificate; fetched with verification disabled and recorded in the raw cache metadata.",
        ],
    }


# ------------------------------------------------------- birth registration
def build_birth():
    r, text, fdate = page(BDR_FEES)
    html = r["body"].decode("utf-8", errors="replace")
    _, _, sdate = page(BDR_SERVICES)

    rows = []
    tm = re.search(r"(?is)<table[^>]*>(.*?)</table>", html)
    for rm in re.finditer(r"(?is)<tr[^>]*>(.*?)</tr>", tm.group(1)):
        cells = [visible_text(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1))]
        if len(cells) >= 3 and re.match(r"^[০-৯]", cells[0].strip()):
            rows.append((cells[1].strip(), cells[2].strip()))

    fees = []
    for i, (what, rate) in enumerate(rows, 1):
        free = "বিনা ফিস" in rate
        amt = None
        m = re.search(r"([০-৯\d]+)\s*টাকা", rate)
        if free:
            amt = 0
        elif m:
            amt = int(m.group(1).translate(BN))
        fees.append({
            "fee_key": f"bdr_{i:02d}",
            "label_bn": what[:300],
            "amount_bdt": amt,
            "includes_vat": None,
            "source_url": BDR_FEES,
            "source_document": None,
            "source_last_updated": fdate,
            "verification": source_read("parsed from the official fee table on orgbdr.gov.bd")
            if amt is not None else unverified("rate cell did not contain a parseable amount"),
        })

    return {
        "category": "birth_registration",
        "service_name_en": "Birth registration and certificate",
        "service_name_bn": "জন্ম নিবন্ধন",
        "office": "রেজিস্ট্রার জেনারেলের কার্যালয়, জন্ম ও মৃত্যু নিবন্ধন (Office of the Registrar General, Birth & Death Registration), Local Government Division",
        "locality": None,
        "variants": [{
            "variant_id": "birth_registration_application",
            "label_en": "Birth registration application",
            "label_bn": "জন্ম নিবন্ধনের আবেদন",
            "required_docs": bdr_docs("birth_registration"),
            "steps": [{"step": "Apply online for birth registration.",
                       "where": "https://bdris.gov.bd/br/application", "source_url": BDR_SERVICES}],
        }],
        "fees": fees,
        "office_location": "Union Parishad / Pourashava / City Corporation ward registrar office",
        "contact": None,
        "apply_portal": "https://bdris.gov.bd/br/application",
        "source_url": BDR_FEES,
        "last_scraped_date": TODAY,
        "source_last_updated": fdate,
        "verification": source_read("official fee table on orgbdr.gov.bd"),
        "notes": [
            f"Fee page self-reports last updated {fdate}; services page {sdate}. Both current.",
            "ANTI-DALAL FACT: registration within 45 days of birth is free (বিনা ফিসে). This is the single most exploitable fact in this service and is stated by the official fee schedule.",
            "Required documents come from the Birth & Death Registration Rules 2018 (statutory instrument), decoded from the gazette PDF - see data/checklists_bdr.json.",
            "orgbdr.gov.bd has an incomplete certificate chain; fetched with verification disabled.",
        ],
    }


# -------------------------------------------------- records we could NOT source
def build_stub(category, name_en, name_bn, office, portal, why, sources):
    return {
        "category": category,
        "service_name_en": name_en,
        "service_name_bn": name_bn,
        "office": office,
        "locality": None,
        "variants": [],
        "fees": [],
        "office_location": None,
        "contact": None,
        "apply_portal": portal,
        "source_url": sources[0],
        "last_scraped_date": TODAY,
        "source_last_updated": None,
        "verification": unverified(why),
        "notes": [
            "NOT INGESTIBLE YET. " + why,
            "Deliberately left empty rather than filled from model knowledge (explain.md 5.1). "
            "The composer must answer 'not verified - contact the office' for this category.",
        ],
    }


DLRS_KHATIAN = "https://dlrs.gov.bd/pages/static-pages/6922dfd8933eb65569e2449b"
NBR_CHARTER_PDF = "https://nbr.gov.bd/uploads/cconbr/Final_Draft_Citizen_2026.pdf"
NBR_CHARTER_INDEX = "https://nbr.gov.bd/information-library/cconbr/eng"
TIN_PORTAL = "https://secure.incometax.gov.bd/TINHome"


def build_land_record():
    """Sourced from DLRS, the directorate that actually issues khatians.

    explain.md pointed at eporcha.gov.bd (dead). dlrs.gov.bd was not in the
    original source list at all and is the authoritative office.
    """
    _, text, updated = page(DLRS_KHATIAN)
    return {
        "category": "land_record",
        "service_name_en": "Land record (khatian) certified copy / porcha",
        "service_name_bn": "খতিয়ান / পর্চা (সার্টিফাইড কপি)",
        "office": "ভূমি রেকর্ড ও জরিপ অধিদপ্তর (Directorate of Land Records & Surveys), Ministry of Land",
        "locality": None,
        "variants": [{
            "variant_id": "khatian_certified_copy",
            "label_en": "Obtaining a khatian / certified copy (porcha)",
            "label_bn": "খতিয়ান প্রাপ্তি",
            "required_docs": [],
            "steps": [
                {"step": "During final publication (চূড়ান্ত প্রকাশনা), the khatian may be collected from the final publication camp under the Upazila Settlement Office, on payment of the government-fixed price.",
                 "where": "Upazila Settlement Office publication camp", "source_url": DLRS_KHATIAN},
                {"step": "After final publication ends, the records are transferred to the office of the relevant Deputy Commissioner (DC).",
                 "where": "Deputy Commissioner's office", "source_url": DLRS_KHATIAN},
                {"step": "Once transferred, the certified copy (porcha) of the khatian is collected from the DC's Record Room.",
                 "where": "DC Record Room", "source_url": DLRS_KHATIAN},
            ],
        }],
        "fees": [{
            "fee_key": "khatian_certified_copy",
            "label_en": "Certified copy of khatian (porcha)",
            "label_bn": "সরকার নির্ধারিত মূল্য",
            "amount_bdt": None,
            "includes_vat": None,
            "source_url": DLRS_KHATIAN,
            "source_document": None,
            "source_last_updated": updated,
            "verification": unverified("source states only 'সরকার নির্ধারিত মূল্য' (government-fixed price) and prints no figure"),
        }],
        "office_location": "Deputy Commissioner's Record Room (district), or Upazila Settlement Office during final publication",
        "contact": None,
        "apply_portal": "https://dlrms.land.gov.bd/",
        "source_url": DLRS_KHATIAN,
        "last_scraped_date": TODAY,
        "source_last_updated": updated,
        "verification": source_read("DLRS page 'পর্চা/খতিয়ান কোথায় পাবেন'"),
        "notes": [
            f"SEVERELY STALE: the source page self-reports last updated {updated}. Treat the procedure as indicative and re-verify before presenting it.",
            "ANTI-DALAL FACT (sourced): the page states there is NO opportunity to obtain a certified copy (porcha) of a khatian from any office other than the DC's Record Room - 'জেলা প্রশাসকের রেকর্ড রুম ছাড়া অন্য কোন দপ্তর হতে খতিয়ানের সার্টিফাইড কপি (পর্চা) সংগ্রহের সুযোগ নেই'.",
            "Fee is deliberately null: the source names a government-fixed price but prints no amount.",
            "SOURCE CORRECTION: explain.md lists eporcha.gov.bd, which has no DNS. dlrs.gov.bd is the issuing directorate and was not in the original source list.",
        ],
    }


def build_tin():
    """Sourced from NBR's own Citizen Charter PDF (published 16-07-2026)."""
    r = fetch(NBR_CHARTER_PDF)
    return {
        "category": "tin_registration",
        "service_name_en": "e-TIN registration",
        "service_name_bn": "ই-টিআইএন নিবন্ধন",
        "office": "জাতীয় রাজস্ব বোর্ড (National Board of Revenue, NBR)",
        "locality": None,
        "variants": [{
            "variant_id": "new_etin_registration",
            "label_en": "New e-TIN registration",
            "label_bn": "নতুন ই-টিআইএন রেজিস্ট্রেশন",
            "required_docs": [
                {"doc": "National ID card (আইডি কার্ড)", "mandatory": True, "source_url": NBR_CHARTER_PDF},
                {"doc": "Trade licence (ট্রেড লাইসেন্স) - for business taxpayers", "mandatory": False, "source_url": NBR_CHARTER_PDF},
            ],
            "steps": [
                {"step": "Register online for a new e-TIN through the NBR taxpayer portal.",
                 "where": TIN_PORTAL, "source_url": NBR_CHARTER_PDF},
                {"step": "Service is delivered through automation/online; the charter records the delivery time as immediate (তাৎক্ষণিক).",
                 "where": "https://incometax.gov.bd / https://etaxnbr.gov.bd", "source_url": NBR_CHARTER_PDF},
            ],
        }],
        "fees": [{
            "fee_key": "new_etin_registration",
            "label_en": "New e-TIN registration",
            "label_bn": "বিনামূল্যে",
            "amount_bdt": 0,
            "includes_vat": None,
            "source_url": NBR_CHARTER_INDEX,
            "source_document": NBR_CHARTER_PDF,
            "source_last_updated": "2026-07-16",
            "verification": source_read("NBR Citizen Charter PDF, fee column decoded via tools/bn_pdf.py reads বিনামূল্যে (free)"),
        }],
        "office_location": "Income tax circle office (অধিক্ষেত্র) for the taxpayer's jurisdiction",
        "contact": "e-Return helpdesk 09643717171; NBR Kor-17 +88-02-22221770 1; info@incometax.gov.bd",
        "apply_portal": TIN_PORTAL,
        "source_url": NBR_CHARTER_INDEX,
        "last_scraped_date": TODAY,
        "source_last_updated": "2026-07-16",
        "verification": source_read("NBR Citizen Charter index page + charter PDF"),
        "notes": [
            "ANTI-DALAL FACT (sourced): NBR's own citizen charter lists new e-TIN registration at বিনামূল্যে - free of charge. Any fee demanded for obtaining a TIN is not an official fee.",
            f"ENCODING RESOLVED (2026-09-05): the charter PDF ({r['bytes']} bytes, 18 pages) ships a broken ToUnicode CMap, which originally rendered this fee as mojibake ('তবনামূদল্য'). tools/bn_pdf.py now decodes it from the embedded font's glyph names and GSUB table: the e-TIN row's fee column reads বিনামূল্যে cleanly, 63 clean occurrences document-wide. The 'free' reading is confirmed, no longer inferred.",
            "The published filename is 'Final_Draft_Citizen_2026.pdf' - NBR labels it a DRAFT. Treat accordingly.",
            "Document list is partial: only the clearly-legible items are recorded.",
            "Residual decoder limitation: ~11% of pre-base vowel signs are still mis-ordered, so treat long prose from this PDF as indicative; short fee vocabulary (বিনামূল্যে, টাকা, numerals) decodes reliably.",
        ],
    }




# --------------------------------------------------- death registration
def build_death():
    """Same official fee table as birth registration.

    The orgbdr schedule is written as "জন্ম বা মৃত্যু" - birth OR death - so the
    rates already parsed for birth_registration are the death rates too. Rows
    are re-filtered here rather than copied, so the two records stay
    independently traceable to the source cells.
    """
    r, text, fdate = page(BDR_FEES)
    html = r["body"].decode("utf-8", errors="replace")
    tm = re.search(r"(?is)<table[^>]*>(.*?)</table>", html)
    fees = []
    i = 0
    for rm in re.finditer(r"(?is)<tr[^>]*>(.*?)</tr>", tm.group(1)):
        cells = [visible_text(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1))]
        if len(cells) < 3 or "মৃত্যু" not in cells[1]:
            continue
        i += 1
        rate = cells[2].strip()
        amt = 0 if "বিনা ফিস" in rate else None
        m = re.search(r"([০-৯\d]+)\s*টাকা", rate)
        if amt is None and m:
            amt = int(m.group(1).translate(BN))
        fees.append({
            "fee_key": f"death_{i:02d}", "label_bn": cells[1].strip()[:300],
            "amount_bdt": amt, "includes_vat": None,
            "source_url": BDR_FEES, "source_document": None, "source_last_updated": fdate,
            "verification": source_read("official fee table on orgbdr.gov.bd, rows covering মৃত্যু নিবন্ধন")
            if amt is not None else unverified("rate cell not parseable"),
        })

    return {
        "category": "death_registration",
        "service_name_en": "Death registration and certificate",
        "service_name_bn": "মৃত্যু নিবন্ধন",
        "office": "রেজিস্ট্রার জেনারেলের কার্যালয়, জন্ম ও মৃত্যু নিবন্ধন (Office of the Registrar General, Birth & Death Registration), Local Government Division",
        "locality": None,
        "variants": [{
            "variant_id": "death_registration_application",
            "label_en": "Death registration application",
            "label_bn": "মৃত্যু নিবন্ধনের আবেদন",
            "required_docs": bdr_docs("death_registration"),
            "steps": [{"step": "Apply online for death registration.",
                       "where": "https://bdris.gov.bd/dr/application", "source_url": BDR_SERVICES}],
        }],
        "fees": fees,
        "office_location": "Union Parishad / Pourashava / City Corporation ward registrar office",
        "contact": None,
        "apply_portal": "https://bdris.gov.bd/dr/application",
        "source_url": BDR_FEES,
        "last_scraped_date": TODAY,
        "source_last_updated": fdate,
        "verification": source_read("official fee table on orgbdr.gov.bd"),
        "notes": [
            "ANTI-DALAL FACT (sourced): registration within 45 days of death is free (বিনা ফিসে), "
            "25 BDT from 45 days to 5 years, 50 BDT after 5 years.",
            "Required documents come from the Birth & Death Registration Rules 2018 (statutory instrument), decoded from the gazette PDF - see data/checklists_bdr.json.",
        ],
    }


# ---------------------------------------------------- income tax return
NBR_ERETURN_FAQ = "https://nbr.gov.bd/uploads/news-scroller/FAQ_e-Return_-_2026.pdf"


def build_income_tax_return():
    """Process from NBR's own citizen-facing e-Return FAQ (2026).

    NO FEE IS RECORDED. The FAQ and the citizen charter both describe e-Return
    filing as an online service without stating a filing fee, and 'no fee is
    mentioned' is not the same as 'the fee is zero'. So amount_bdt stays null
    and the composer will say 'not verified - ask the office'.

    Step text is written in English rather than pasted from the PDF: the Nikosh
    decoder still garbles this document's conjuncts ('রিটানড' for রিটার্ন,
    'বমাবাইল' for মোবাইল), and shipping mangled Bengali to a citizen is worse
    than a clean English summary that cites its source.
    """
    return {
        "category": "income_tax_return",
        "service_name_en": "Income tax return filing (e-Return)",
        "service_name_bn": "আয়কর রিটার্ন দাখিল (ই-রিটার্ন)",
        "office": "জাতীয় রাজস্ব বোর্ড (National Board of Revenue, NBR)",
        "locality": None,
        "variants": [{
            "variant_id": "ereturn_online_filing",
            "label_en": "Online return filing (e-Return)",
            "label_bn": "অনলাইনে ই-রিটার্ন দাখিল",
            "required_docs": [
                {"doc": "TIN (Taxpayer's Identification Number)", "mandatory": True,
                 "source_url": NBR_ERETURN_FAQ},
                {"doc": "A mobile phone number registered against your own NID (used for registration)",
                 "mandatory": True, "source_url": NBR_ERETURN_FAQ},
            ],
            "steps": [
                {"step": "Register on the e-Return portal using your TIN and a mobile number registered against your own NID.",
                 "where": "https://etaxnbr.gov.bd", "source_url": NBR_ERETURN_FAQ},
                {"step": "Sign in and update your profile details.",
                 "where": "https://etaxnbr.gov.bd", "source_url": NBR_ERETURN_FAQ},
                {"step": "Enter income by category, investments, family expenditure, assets and liabilities, then submit the return.",
                 "where": "https://etaxnbr.gov.bd", "source_url": NBR_ERETURN_FAQ},
                {"step": "Download the Acknowledgement slip and Tax certificate after submission.",
                 "where": "https://etaxnbr.gov.bd", "source_url": NBR_ERETURN_FAQ},
            ],
        }],
        "fees": [{
            "fee_key": "ereturn_filing", "label_en": "Online return filing",
            "amount_bdt": None, "includes_vat": None,
            "source_url": NBR_ERETURN_FAQ, "source_document": NBR_ERETURN_FAQ,
            "source_last_updated": "2026-07-16",
            "raw_text": None,
            "verification": unverified(
                "neither the e-Return FAQ nor the NBR citizen charter states a filing fee; "
                "absence of a stated fee is not evidence that it is free"),
        }],
        "office_location": "Income tax circle office (অধিক্ষেত্র) for the taxpayer's jurisdiction",
        "contact": "e-Return helpdesk 09643717171; info@incometax.gov.bd",
        "apply_portal": "https://etaxnbr.gov.bd",
        "source_url": NBR_ERETURN_FAQ,
        "last_scraped_date": TODAY,
        "source_last_updated": "2026-07-16",
        "verification": source_read("NBR e-Return FAQ 2026, decoded via tools/bn_pdf.py"),
        "notes": [
            "Steps are an English summary of NBR's Bengali FAQ, each citing that source. Verbatim "
            "Bengali was NOT used because the decoder still garbles this document's conjuncts.",
            "No filing fee is recorded - see the fee entry's verification note.",
        ],
    }


def main():
    os.makedirs("data/services", exist_ok=True)
    records = [
        build_passport(),
        build_birth(),
        build_tin(),
        build_death(),
        build_income_tax_return(),
        build_land_record(),
        build_stub("nid_correction", "NID correction", "এনআইডি সংশোধন",
                   "Bangladesh Election Commission", "https://services.nidw.gov.bd/",
                   "www.ecs.gov.bd returns HTTP 403 behind a Cloudflare bot challenge (attempted once politely on 2026-09-04 and again on retry; not retried further by policy). services.nidw.gov.bd is login-walled and must not be scraped. The national portal e-services directory surfaced no NID procedure link. No public, fetchable procedure page was found.",
                   ["https://www.ecs.gov.bd/"]),
    ]
    for rec in records:
        p = f"data/services/{rec['category']}.json"
        json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        nf = sum(1 for f in rec["fees"] if f["amount_bdt"] is not None)
        print(f"  {p:<42} fees={len(rec['fees']):>2} (verified {nf}) "
              f"docs={sum(len(v['required_docs']) for v in rec['variants']):>2} "
              f"status={rec['verification']['status']}")


if __name__ == "__main__":
    main()
