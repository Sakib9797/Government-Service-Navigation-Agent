"""
Vector search over the chunk index, filtered by service category.

The category filter is the point: explain.md's Retrieval Agent searches
"filtered by classified category" so a passport question can never surface a
land-office chunk. Filtering is applied by over-fetching then masking, which
keeps results exact for an index this size and needs no ID-selector plumbing.
"""
import json
import os

import faiss

from rag.embed_and_index import INDEX_DIR, encode_query

_index = None
_meta = None


def load(index_dir=INDEX_DIR):
    global _index, _meta
    if _index is None:
        _index = faiss.read_index(os.path.join(index_dir, "chunks.faiss"))
        _meta = json.load(open(os.path.join(index_dir, "chunks.json"), encoding="utf-8"))
    return _index, _meta


def search(query, category=None, k=5, oversample=8):
    """Return up to k chunks, restricted to `category` when given."""
    index, meta = load()
    chunks = meta["chunks"]
    qv = encode_query(query)
    n = min(len(chunks), k * oversample if category else k)
    scores, ids = index.search(qv, n)

    out = []
    for score, i in zip(scores[0], ids[0]):
        if i < 0:
            continue
        c = chunks[i]
        if category and c["meta"]["category"] != category:
            continue
        out.append({"score": float(score), "id": c["id"], "text": c["text"], "meta": c["meta"]})
        if len(out) >= k:
            break
    return out


if __name__ == "__main__":
    for q, cat in [("আমার জমির খতিয়ান দরকার, কী করতে হবে?", None),
                   ("How do I renew my passport?", "passport"),
                   ("passport er jonno ki ki lagbe", "passport")]:
        print(f"\nQ: {q}  (filter={cat})")
        for r in search(q, category=cat, k=3):
            print(f"  {r['score']:.3f}  {r['meta']['chunk_kind']:<14} {r['text'][:88]}")
