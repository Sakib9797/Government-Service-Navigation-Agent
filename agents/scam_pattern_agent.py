"""Agent 4: curated scam-pattern lookup. NEVER generative.

explain.md 5.3: hallucinated scam claims could mislead users or defame a
legitimate office. This agent does a dictionary lookup against a human-curated,
sourced table and returns entries verbatim. There is no model call here, by
design - if the table has nothing for a category, the answer is nothing.
"""
import json

TABLE = "agents/scam_patterns.json"
_t = None


def table():
    global _t
    if _t is None:
        _t = json.load(open(TABLE, encoding="utf-8"))
    return _t


def lookup(category):
    return [p for p in table()["patterns"] if p["category"] == category]
