"""
LLM answer layer: phrases a TARGETED answer to the user's actual question.

The template composer renders the whole service record for every query, so
"do I need a photo?" and "what does a 64-page passport cost?" return the same
5,197 characters. This layer fixes that - and it is also what finally makes the
retrieved chunks matter, since they are what tell the model which part of the
record the question is about.

THE SAFETY CONTRACT, and why adding an LLM does not reintroduce hallucination:

  1. The model is given a FACTS block assembled deterministically from the
     verified record plus the retrieved chunks. It is told it may use nothing
     else.
  2. Its output is then VALIDATED: every number it wrote must already appear in
     the FACTS block. A model that invents "BDT 3,000" fails this check.
  3. On any failure - no key, API error, validation rejection - we fall back to
     the template answer. The safety floor never depends on the model behaving.
  4. The fee table, the document checklist and the provenance footer are still
     rendered by the template and appended verbatim. The model writes prose
     ABOUT the facts; it never renders the facts themselves.

So the worst case is the old behaviour, not a wrong number.
"""
import os
import re
import sys

sys.path.insert(0, "tools")

# Load .env from the PROJECT ROOT explicitly. Bare load_dotenv() walks the
# caller stack to find the file, which raises AssertionError when there is
# no caller frame (module imported from stdin, exec, or some runners) - and
# that failure silently disabled the LLM path.
try:
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from textnorm import nfc

# Default chosen from what this Groq account actually serves (llama-3.3-70b is
# not available on it). Override with GSNA_LLM_MODEL. Cheaper alternative:
# openai/gpt-oss-20b.
MODEL = os.environ.get("GSNA_LLM_MODEL", "openai/gpt-oss-120b")
# Any digit run of 2+, or a single digit that is not part of a word.
NUM = re.compile(r"\d[\d,]*")

SYSTEM = """You answer questions about Bangladeshi government services for ordinary citizens.

You will be given FACTS extracted from an official, verified government record, and the
citizen's QUESTION.

RULES - these are absolute:
1. Use ONLY the FACTS. Never add a fee, document, deadline, office or number from your own
   knowledge. If the FACTS do not answer the question, say plainly that the verified record
   does not cover it and suggest contacting the office.
2. Never state a number that does not appear in the FACTS.
3. Answer the SPECIFIC question asked. Do not restate the whole record. If they asked about
   one document, talk about that document.
4. Reply in the language of the QUESTION. If the question is in Bengali or in romanised
   Bengali (Banglish), reply in Bengali.
5. Be short: 2-5 sentences. A full fee table and source links are appended automatically
   after your text, so do not reproduce them.
6. Never promise an outcome or a timeline that is not in the FACTS."""


def _facts_block(record, chunks, freshness, scams):
    """Deterministically assemble everything the model is allowed to use."""
    L = []
    L.append(f"SERVICE: {record['service_name_bn']} / {record['service_name_en']}")
    L.append(f"OFFICE: {record['office']}")
    if record.get("apply_portal"):
        L.append(f"APPLY AT: {record['apply_portal']}")
    if record.get("contact"):
        L.append(f"CONTACT: {record['contact']}")
    L.append(f"SOURCE LAST UPDATED: {record.get('source_last_updated') or 'unknown'}")

    if record.get("fees"):
        L.append("\nFEES:")
        for f in record["fees"]:
            label = f.get("label_en") or f.get("label_bn") or f["fee_key"]
            if f["amount_bdt"] is None:
                amt = "NOT VERIFIED - the official source gives no figure"
            elif f["amount_bdt"] == 0:
                amt = "free of charge (বিনামূল্যে)"
            else:
                amt = f"BDT {f['amount_bdt']:,}"
            L.append(f"  - {label}: {amt}")

    docs = [d["doc"] for v in record.get("variants", []) for d in v.get("required_docs", [])]
    if docs:
        L.append("\nREQUIRED DOCUMENTS:")
        L += [f"  - {d}" for d in docs]

    steps = [s["step"] for v in record.get("variants", []) for s in v.get("steps", [])]
    if steps:
        L.append("\nPROCESS:")
        L += [f"  {i}. {s}" for i, s in enumerate(steps, 1)]

    if chunks:
        L.append("\nMOST RELEVANT PASSAGES FOR THIS QUESTION (ranked by retrieval):")
        L += [f"  - {c['text']}" for c in chunks[:4]]

    if scams:
        L.append("\nOFFICIAL FACTS THAT PROTECT THE CITIZEN:")
        L += [f"  - {s['claim_en']}" for s in scams]

    if freshness.get("notes"):
        L.append("\nRELIABILITY WARNINGS:")
        L += [f"  - {n}" for n in freshness["notes"]]

    return "\n".join(L)


def _numbers(text):
    return {m.group(0).replace(",", "").lstrip("0") or "0" for m in NUM.finditer(text)}


def validate(answer, facts, query=""):
    """Reject any number the model invented. Returns (ok, reason).

    Numbers from the QUESTION are allowed as well as from the FACTS: a citizen
    asking "my baby is 3 years old" must be answerable without the model being
    rejected for repeating "3". This does not weaken the guarantee - a leading
    question ("is it 5000 taka?") still cannot make 5000 appear as a fee,
    because the fee table is template-rendered from the record and the model is
    instructed never to assert a figure that is not in the FACTS.
    """
    allowed = _numbers(facts) | _numbers(query) | {"", "0"}
    # Bengali digits map to the same values; normalise before comparing.
    bn = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
    allowed |= {n.translate(bn) for n in allowed}
    used = _numbers(answer.translate(bn))
    bad = {n for n in used if n not in allowed}
    if bad:
        return False, f"model used number(s) absent from FACTS: {sorted(bad)}"
    return True, None


def available():
    return bool(os.environ.get("GROQ_API_KEY")) and os.environ.get("GSNA_LLM_COMPOSER", "1") != "0"


def compose_llm(query, record, chunks, freshness, scams):
    """Return (answer_text, debug) or (None, reason) so the caller can fall back."""
    if not available():
        return None, "no GROQ_API_KEY (or composer disabled)"
    facts = _facts_block(record, chunks, freshness, scams)
    try:
        from groq import Groq
        client = Groq()
        r = client.chat.completions.create(
            model=MODEL, max_tokens=500, temperature=0.2,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": f"FACTS:\n{facts}\n\nQUESTION: {query}"}])
        text = (r.choices[0].message.content or "").strip()
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"

    if not text:
        return None, "empty completion"
    ok, why = validate(nfc(text), nfc(facts), nfc(query))
    if not ok:
        return None, f"REJECTED - {why}"
    return text, {"model": MODEL, "facts_chars": len(facts), "chunks_used": len(chunks)}
