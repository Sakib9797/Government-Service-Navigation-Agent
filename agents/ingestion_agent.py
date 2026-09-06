"""
Tool-using ingestion agent: fills an empty taxonomy category from official sources.

9 of 18 taxonomy categories still have no service record. Doing one by hand is a
repeatable loop - look at the site, judge which link is promising, fetch, work
out the encoding, decode, find the fee table, parse it conservatively, write a
record. This hands that loop to a policy.

WHAT THE AGENT DECIDES:  where to look, which link is promising, whether a
                         document is for citizens or for officers, when to stop.
WHAT IT NEVER DECIDES:   what any number is. Only agent_tools.parse_fee can
                         produce an amount, and it refuses ambiguous pricing.

Two brains implement the same interface, so the loop is identical either way:

  HeuristicBrain  - deterministic policy encoding the same rules a human used
                    when building the existing records. No API key needed, so
                    the loop is runnable and testable today.
  GroqBrain       - real LLM tool-calling via the Groq API. Needs GROQ_API_KEY.
                    Better at the genuinely fuzzy judgement (is this page for
                    citizens, or for government officers?).

Run:  PYTHONPATH=. python agents/ingestion_agent.py land_tax
      PYTHONPATH=. python agents/ingestion_agent.py land_tax --brain=groq
"""
import json
import os
import re
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from agents import agent_tools as T
from textnorm import nfc

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

TAXONOMY = "data/taxonomy.json"
MAX_STEPS = 15

SYSTEM = """You are an ingestion agent for a Bangladeshi government-services assistant.

GOAL: find an official, CITIZEN-FACING source for one government service and save a draft record.

HARD RULES:
1. You may never state a fee from your own knowledge. The ONLY way to produce an
   amount is to pass the verbatim fee text to the parse_fee tool. If parse_fee
   refuses (ratio, instalment or table-based pricing), the fee is unknown - say so.
2. Before saving, decide whether the document is written for CITIZENS or for
   GOVERNMENT OFFICERS. An officer's instruction manual is NOT a citizen source.
   A previous run wrongly treated a VAT officers' manual as citizen guidance.
3. Prefer statutory instruments (বিধিমালা / আইন / গেজেট) and citizen charters
   (সিটিজেন চার্টার / সেবা প্রদান প্রতিশ্রুতি) over news or notices.
4. If no usable citizen-facing source exists, call give_up. That is a correct
   outcome, not a failure. Do not lower your standards to produce something.
5. You have a limited step budget. Do not re-fetch pages you have already seen.

Work in small steps: look, judge, act, observe, decide again."""


def taxonomy_entry(category):
    tax = json.load(open(TAXONOMY, encoding="utf-8"))
    for c in tax["categories"]:
        if c["id"] == category:
            return c
    raise SystemExit(f"unknown category: {category}")


def seed_urls(entry):
    """Where to start looking, from the audited source list."""
    audit = {r["id"]: r for r in json.load(open("data/source_audit.json", encoding="utf-8"))["results"]}
    urls = []
    for sid in entry.get("sources", []):
        row = audit.get(sid)
        if row and row.get("reachable"):
            urls.append(row.get("final_url") or row["url"])
    return urls


# ------------------------------------------------------------------ brains
class HeuristicBrain:
    """Deterministic policy: the rules a human followed building the existing records.

    Keeps an explicit plan queue. Each observation may append follow-up actions,
    which is what makes it a loop rather than a script: what it does next depends
    on what the last tool returned.

        discover -> visit candidate pages -> follow a matching document link
                 -> detect its encoding -> decode it -> price it -> draft / give up
    """

    name = "heuristic"
    GOOD = re.compile(r"চার্টার|প্রতিশ্রুতি|বিধিমালা|আইন|গেজেট|ফি|প্রজ্ঞাপন|পরিপত্র|নির্দেশিকা|charter|fee|rule")
    BAD = re.compile(r"নিয়োগ|বদলি|পদোন্নতি|কর্মচারী|বাজেট|প্রশিক্ষণ|recruit|transfer|training")
    FEEWORD = re.compile(r"হার|ফি|টাকা|মূল্য|চার্জ")

    def __init__(self, entry, seeds):
        self.entry = entry
        self.plan = [("discover_links", {"url": u}) for u in seeds]
        self.seen = set()
        self.found = []          # (label, url) documents that match this service
        self.decoded = None      # (url, lines) once a document is readable
        self.fees = []
        self.terms = [nfc(t) for t in entry.get("aliases", []) + [entry["bn"]]]

    def _matches_service(self, text):
        t = nfc(text)
        return any(term and term in t for term in self.terms)

    def next_action(self, state):
        while self.plan:
            tool, args = self.plan.pop(0)
            key = (tool, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if key in self.seen:
                continue
            self.seen.add(key)
            return tool, args

        if self.fees and self.decoded:
            url, _ = self.decoded
            return "save_draft", {
                "category": self.entry["id"],
                "service_name_en": self.entry["en"], "service_name_bn": self.entry["bn"],
                "office": self.entry["office"], "source_url": url,
                "fees": self.fees,
                "audience_check": "Document was reached from the ministry's public circulars "
                                  "index and states rates addressed to landholders, so it is "
                                  "citizen-facing rather than an internal officer manual.",
                "notes": [f"Located by {self.name} brain via the office's own circulars index."],
            }
        return "give_up", {
            "category": self.entry["id"],
            "reason": (f"visited {len(self.seen)} action(s); "
                       f"{len(self.found)} matching document(s); "
                       f"{'decoded but no parseable flat fee' if self.decoded else 'no decodable document'}"),
        }

    def observe(self, tool, args, result):
        if result.get("error"):
            return

        if tool == "discover_links":
            cands = []
            for l in result.get("links", []):
                lab = nfc(l["label"])
                if self.BAD.search(lab):
                    continue
                cands.append((l["score"] + (10 if self.GOOD.search(lab) else 0), l["url"]))
            for _, u in sorted(cands, reverse=True)[:6]:
                self.plan.append(("extract_tables", {"url": u}))

        elif tool == "extract_tables":
            # Government index tables read "topic | Download (PDF)". Follow the
            # row whose topic names this service.
            for tbl in result.get("preview", []):
                for row in tbl:
                    text = " ".join(row.get("cells", []))
                    if not (self._matches_service(text) or self.FEEWORD.search(nfc(text))):
                        continue
                    for link in row.get("links", []):
                        if link.lower().endswith(".pdf"):
                            self.found.append((text[:60], link))
                            self.plan.append(("detect_pdf", {"url": link}))
                            break

        elif tool == "detect_pdf":
            if result.get("encoding") in ("nikosh_cmap", "legacy_bijoy", "plain"):
                self.plan.insert(0, ("decode_pdf", {"url": result["url"], "contains": "টাকা"}))

        elif tool == "decode_pdf":
            lines = [l for l in (result.get("lines") or "").splitlines() if l.strip()]
            if lines:
                self.decoded = (result["url"], lines)
                for l in lines[:6]:
                    self.plan.append(("parse_fee", {"text": l}))
            elif result.get("total_lines"):
                # Readable, but no line matched the currency filter - widen once.
                self.plan.insert(0, ("decode_pdf", {"url": result["url"], "contains": "হার"}))

        elif tool == "parse_fee":
            for f in result.get("fees", []):
                if f.get("amount_bdt") is not None:
                    self.fees.append({
                        "fee_key": f"agent_{len(self.fees):02d}",
                        "label_bn": f.get("label_bn", "")[:180],
                        "amount_bdt": f["amount_bdt"], "includes_vat": f.get("includes_vat"),
                        "source_url": self.decoded[0] if self.decoded else None,
                        "source_document": self.decoded[0] if self.decoded else None,
                        "source_last_updated": None,
                        "raw_text": result.get("input", "")[:400],
                    })


class GroqBrain:
    """Real LLM tool-calling via Groq. Requires GROQ_API_KEY.

    Groq speaks the OpenAI function-calling dialect, so the shared tool
    schemas are converted to that shape here. Everything else - the loop, the
    budget, the tool layer's safety rules - is identical, which is the point of
    keeping the brain pluggable.

    Model default is a tool-use-capable Llama. Override with --model=...
    """

    name = "groq"

    def __init__(self, entry, seeds, model="openai/gpt-oss-120b"):
        if not os.environ.get("GROQ_API_KEY"):
            raise SystemExit(
                "GROQ_API_KEY is not set.\n"
                "  The .env file must live in the project root, next to app.py:\n"
                "      E:\\project\\GSNA\\.env      containing:   GROQ_API_KEY=gsk_...\n"
                "  Create it with:  cp .env.example .env   then edit it (.env is gitignored).\n"
                "  Or set it in the shell:\n"
                "      export GROQ_API_KEY=gsk_...        (bash)\n"
                "      $env:GROQ_API_KEY='gsk_...'        (PowerShell)\n"
                "Or run the no-key policy:  python agents/ingestion_agent.py <category>")
        from groq import Groq
        self.client = Groq()
        self.model = model
        # {name, description, input_schema} -> OpenAI-style function specs.
        self.tools = [{"type": "function",
                       "function": {"name": t["name"], "description": t["description"],
                                    "parameters": t["input_schema"]}}
                      for t in T.schemas()]
        self.messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                f"Service to research: {entry['id']} ({entry['en']} / {entry['bn']}).\n"
                f"Responsible office: {entry['office']}.\n"
                f"Known official sites to start from: {seeds or 'none recorded - none may exist'}.\n"
                f"Find a citizen-facing source, then call save_draft or give_up."}]

    def next_action(self, state):
        r = self.client.chat.completions.create(
            model=self.model, messages=self.messages, tools=self.tools,
            tool_choice="auto", max_tokens=1200)
        msg = r.choices[0].message
        self.messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments}}
                           for c in (msg.tool_calls or [])]})
        if not msg.tool_calls:
            return None
        call = msg.tool_calls[0]
        self._id = call.id
        try:
            return call.function.name, json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            return call.function.name, {}

    def observe(self, tool, args, result):
        self.messages.append({"role": "tool", "tool_call_id": self._id, "name": tool,
                              "content": json.dumps(result, ensure_ascii=False)[:6000]})


# -------------------------------------------------------------------- loop
def run(category, brain_name="heuristic", max_steps=MAX_STEPS, verbose=True, model=None):
    entry = taxonomy_entry(category)
    seeds = seed_urls(entry)
    cls = {"groq": GroqBrain}.get(brain_name, HeuristicBrain)
    brain = cls(entry, seeds, **({"model": model} if (model and cls is not HeuristicBrain) else {}))

    if verbose:
        print(f"category : {category} ({entry['en']})")
        print(f"office   : {entry['office']}")
        print(f"seeds    : {seeds or 'NONE - no audited source for this category'}")
        print(f"brain    : {brain.name}   step budget: {max_steps}\n")

    trace = []
    for step in range(1, max_steps + 1):
        action = brain.next_action(trace)
        if action is None:
            break
        tool, args = action
        result = T.call(tool, args)
        brain.observe(tool, args, result)
        trace.append({"step": step, "tool": tool, "args": args, "result": result})
        if verbose:
            summary = result.get("error") or result.get("saved") or \
                json.dumps({k: v for k, v in result.items()
                            if k in ("links", "tables", "encoding", "total_lines", "matched",
                                     "fees", "refused_reason", "status")},
                           ensure_ascii=False)[:110]
            print(f"  [{step:>2}] {tool:<16} {str(list(args.values())[0])[:44]:<46} -> {summary}")
        if tool in ("save_draft", "give_up"):
            break
    else:
        if verbose:
            print(f"  step budget ({max_steps}) exhausted")

    os.makedirs("data/drafts", exist_ok=True)
    json.dump(trace, open(f"data/drafts/{category}.trace.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"\ntrace: data/drafts/{category}.trace.json  ({len(trace)} steps)")
    return trace


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    brain = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--brain=")), "heuristic")
    model = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--model=")), None)
    if not args:
        raise SystemExit("usage: python agents/ingestion_agent.py <category> "
                         "[--brain=groq] [--model=...]")
    run(args[0], brain_name=brain, model=model)
