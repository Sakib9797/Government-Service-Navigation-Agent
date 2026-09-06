"""Agent 2: category-filtered vector search, plus the full record for the composer.

Returns BOTH the retrieved chunks and the raw service record. The record matters
because fees are read from it directly - they are never taken from a retrieved
chunk (see rag/chunker.py).
"""
import json
import os

from rag.retriever import search

SERVICES = "data/services"


def load_record(category):
    p = os.path.join(SERVICES, f"{category}.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def retrieve(query, category, k=5):
    if category in ("unknown_service", "out_of_scope"):
        return {"chunks": [], "record": None}
    return {"chunks": search(query, category=category, k=k), "record": load_record(category)}
