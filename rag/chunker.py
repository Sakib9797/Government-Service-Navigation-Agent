"""
Turn service records into retrieval chunks.

Two rules that differ from a naive RAG build:

1. Chunk by SERVICE, never by raw page (explain.md Phase 2). A page mixes
   unrelated procedures; a chunk that spans two services produces answers that
   blend a passport requirement into a land question.

2. Fee AMOUNTS are NOT embedded. Chunks describe what a service is and how it
   works; the numbers live in the record's keyed `fees` array and are read
   directly by the composer. Retrieving a number by embedding similarity is the
   easiest way to state the wrong one, and a wrong fee costs a real person money
   (explain.md 5.1). Fee LABELS are included so "what does a passport cost"
   still retrieves the passport service - it just does not carry the digits.
"""
import glob
import json
import os


def chunks_for(rec):
    """Yield (chunk_id, text, metadata) for one service record."""
    cat = rec["category"]
    base = {
        "category": cat,
        "service_name_en": rec["service_name_en"],
        "service_name_bn": rec["service_name_bn"],
        "office": rec["office"],
        "source_url": rec["source_url"],
        "source_last_updated": rec.get("source_last_updated"),
        "last_scraped_date": rec["last_scraped_date"],
        "verification_status": rec["verification"]["status"],
    }

    # 1. Identity chunk - what this service is and who runs it.
    yield (f"{cat}::identity",
           f"{rec['service_name_bn']} | {rec['service_name_en']} | {rec['office']}",
           {**base, "chunk_kind": "identity"})

    for v in rec.get("variants", []):
        vid = v["variant_id"]

        # 2. Steps chunk - the process, kept together so ordering survives.
        if v.get("steps"):
            body = " ".join(f"{i}. {s['step']}" for i, s in enumerate(v["steps"], 1))
            yield (f"{cat}::{vid}::steps",
                   f"{rec['service_name_bn']} {v.get('label_en','')} — process: {body}",
                   {**base, "chunk_kind": "steps", "variant_id": vid})

        # 3. Document chunks - one per requirement, so a question about a single
        #    document ("do I need my old passport?") retrieves that line, not a
        #    2,000-character blob.
        for i, d in enumerate(v.get("required_docs", [])):
            yield (f"{cat}::{vid}::doc{i}",
                   f"{rec['service_name_bn']} {v.get('label_en','')} — required document: {d['doc']}",
                   {**base, "chunk_kind": "required_doc", "variant_id": vid,
                    "doc_source_url": d.get("source_url")})

    # 4. Fee-LABEL chunk. Labels only, never amounts - see module docstring.
    if rec.get("fees"):
        labels = " / ".join(f.get("label_en") or f.get("label_bn") or f["fee_key"] for f in rec["fees"])
        yield (f"{cat}::fee_labels",
               f"{rec['service_name_bn']} {rec['service_name_en']} — fee categories: {labels}",
               {**base, "chunk_kind": "fee_labels",
                "note": "amounts deliberately excluded from the index; read them from the record"})


def load_records(path="data/services"):
    return [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(path, "*.json")))]


def build_chunks(records=None):
    records = records if records is not None else load_records()
    out = []
    for rec in records:
        for cid, text, meta in chunks_for(rec):
            out.append({"id": cid, "text": text, "meta": meta})
    return out


if __name__ == "__main__":
    cs = build_chunks()
    by_kind = {}
    for c in cs:
        by_kind[c["meta"]["chunk_kind"]] = by_kind.get(c["meta"]["chunk_kind"], 0) + 1
    print(f"{len(cs)} chunks from {len(load_records())} records")
    for k, n in sorted(by_kind.items()):
        print(f"  {k:<16}{n:>4}")
    assert not any(ch in c["text"] for c in cs for ch in ("4025", "6325", "13800")), \
        "fee amount leaked into an embedded chunk"
    print("\ncheck passed: no fee amounts in chunk text")
