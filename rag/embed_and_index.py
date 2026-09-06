"""
Embed service chunks and build the FAISS index.

Model: a multilingual sentence encoder, because real queries are code-mixed
Bengali/English and often romanised Banglish (explain.md 5.4). Verified on this
data: "আমার জমির খতিয়ান দরকার" vs "I need my land record document" scores 0.92.

MODEL_NAME is the seam. explain.md suggests BAAI/bge-m3 or
intfloat/multilingual-e5-large; multilingual-e5-small is the default here
because it is ~0.5GB instead of ~2.2GB and runs on CPU. Swap the constant and
re-run - nothing downstream changes.

e5 models require asymmetric prefixes ("query: " / "passage: "). Getting this
wrong silently degrades retrieval, so it is handled in one place.
"""
import json
import os

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rag.chunker import build_chunks

MODEL_NAME = os.environ.get("GSNA_EMBED_MODEL", "intfloat/multilingual-e5-small")
INDEX_DIR = "rag/index"
_model = None


def model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _needs_prefix():
    return "e5" in MODEL_NAME.lower()


def encode_passages(texts):
    t = [f"passage: {x}" for x in texts] if _needs_prefix() else list(texts)
    return model().encode(t, normalize_embeddings=True, convert_to_numpy=True).astype("float32")


def encode_query(q):
    t = f"query: {q}" if _needs_prefix() else q
    return model().encode([t], normalize_embeddings=True, convert_to_numpy=True).astype("float32")


def build(out_dir=INDEX_DIR):
    chunks = build_chunks()
    vecs = encode_passages([c["text"] for c in chunks])
    # Inner product on L2-normalised vectors == cosine similarity.
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)

    os.makedirs(out_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(out_dir, "chunks.faiss"))
    json.dump({"model": MODEL_NAME, "dim": int(vecs.shape[1]), "chunks": chunks},
              open(os.path.join(out_dir, "chunks.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return len(chunks), int(vecs.shape[1])


if __name__ == "__main__":
    n, d = build()
    print(f"indexed {n} chunks, dim={d}, model={MODEL_NAME}")
    print(f"wrote {INDEX_DIR}/chunks.faiss and chunks.json")
