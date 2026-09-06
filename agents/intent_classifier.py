"""
Agent 1: map a free-text query onto the FIXED taxonomy.

Design: the classifier can only ever emit an id from data/taxonomy.json, or one
of the two fallbacks. A fixed taxonomy is what stops the system inventing
service categories (explain.md agent table), and the fallbacks are what stop it
forcing a near-miss - sending a citizen to the wrong office is the failure this
whole project exists to prevent.

Method: exact alias match first (cheap, exact, handles "khatian", "e-TIN"),
then multilingual embedding similarity against each category's label+alias
profile. Below CONFIDENCE_FLOOR the answer is unknown_service, deliberately.

LLM SEAM: explain.md specifies a small fast LLM call here. This implementation
is embedding-based so it runs with no API key and is deterministic, which also
makes it testable. To swap in an LLM, replace classify() and keep the contract:
return an id from the taxonomy or a fallback, never free text.
"""
import json
import re

import numpy as np

import sys, os
sys.path.insert(0, "tools")
from textnorm import nfc

from rag.embed_and_index import encode_passages, encode_query

TAXONOMY = "data/taxonomy.json"
CONFIDENCE_FLOOR = 0.80      # below this we say we do not know
MARGIN = 0.015               # top-2 must differ by this or it is ambiguous

_tax = None
_profiles = None
_vecs = None


def taxonomy():
    global _tax
    if _tax is None:
        _tax = json.load(open(TAXONOMY, encoding="utf-8"))
    return _tax


def _build_profiles():
    global _profiles, _vecs
    if _vecs is not None:
        return _profiles, _vecs
    cats = taxonomy()["categories"]
    _profiles = [{"id": c["id"], "bn": c["bn"], "en": c["en"], "office": c["office"],
                  "aliases": c["aliases"]} for c in cats]
    texts = [f"{c['bn']} | {c['en']} | {c['office']} | {' | '.join(c['aliases'])}" for c in cats]
    _vecs = encode_passages(texts)
    return _profiles, _vecs


def _norm(s):
    return nfc(re.sub(r"\s+", " ", s.lower().strip()))


def alias_hits(query):
    """All categories with an alias contained in the query, longest alias per category.

    Returning ALL hits (not just the longest overall) matters: 'correct date of
    birth on national id' hits nid_new via the generic 'national id' and
    nid_correction via 'correct date of birth'. Longest-wins picked nid_new and
    sent the user to the wrong service. When several categories match, the tie
    is broken by embedding similarity among only those candidates.
    """
    q = _norm(query)
    hits = {}
    for c in taxonomy()["categories"]:
        for a in c["aliases"]:
            an = _norm(a)
            if an and an in q and len(an) > len(hits.get(c["id"], "")):
                hits[c["id"]] = an
    return hits


def classify(query):
    """Return {category, confidence, method, rationale}."""
    hits = alias_hits(query)
    if len(hits) == 1:
        cid, alias = next(iter(hits.items()))
        return {"category": cid, "confidence": 1.0, "method": "alias",
                "rationale": f"matched alias '{alias}'"}

    profiles, vecs = _build_profiles()

    if len(hits) > 1:
        idx = [i for i, p in enumerate(profiles) if p["id"] in hits]
        sims = vecs[idx] @ encode_query(query)[0]
        win = idx[int(np.argmax(sims))]
        return {"category": profiles[win]["id"], "confidence": float(np.max(sims)),
                "method": "alias+embedding",
                "rationale": f"aliases matched {sorted(hits)}; embedding chose {profiles[win]['id']}"}

    sims = (vecs @ encode_query(query)[0])
    order = np.argsort(-sims)
    top, second = int(order[0]), int(order[1])
    score, gap = float(sims[top]), float(sims[top] - sims[second])

    if score < CONFIDENCE_FLOOR:
        return {"category": "unknown_service", "confidence": score, "method": "embedding",
                "rationale": f"best match {profiles[top]['id']} scored {score:.3f}, below floor {CONFIDENCE_FLOOR}"}
    if gap < MARGIN:
        return {"category": "unknown_service", "confidence": score, "method": "embedding",
                "rationale": f"ambiguous between {profiles[top]['id']} and {profiles[second]['id']} "
                             f"(gap {gap:.3f} < {MARGIN})"}
    return {"category": profiles[top]["id"], "confidence": score, "method": "embedding",
            "rationale": f"nearest category profile (gap {gap:.3f})"}


if __name__ == "__main__":
    for q in ["আমার জমির খতিয়ান দরকার, কী করতে হবে?",
              "How do I renew my passport and how much does it cost?",
              "NID তে আমার নাম ভুল আছে, কীভাবে ঠিক করব?",
              "jonmo nibondhon korte ki lage",
              "TIN khulte koto taka lage",
              "what is the capital of France"]:
        r = classify(q)
        print(f"  {r['category']:<20} {r['confidence']:.3f} {r['method']:<10} {q[:44]}")
