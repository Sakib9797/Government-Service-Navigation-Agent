# Government Service Navigation Agent (Bangladesh)

## 1. Project Purpose

This project is an AI agent system that helps Bangladeshi citizens figure out
**which government service they need, what documents/fees are required, and
how to avoid common middleman ("dalal") scams** — all explained in plain
Bengali or English.

**Problem it solves:** Government service processes in Bangladesh (passport,
NID correction, land records/khatian, trade license, driving license, birth
certificate, TIN/tax) are scattered across many different portals, often
poorly documented, and change without clear public notice. Citizens without
prior experience frequently pay unnecessary middleman fees or go to the wrong
office because they can't easily find authoritative, current, plain-language
guidance.

**Target user:** Any Bangladeshi citizen typing/speaking a natural-language
question like:
- "আমার জমির খতিয়ান দরকার, কী করতে হবে?" (I need my land record, what do I do?)
- "How do I renew my passport and how much does it cost?"
- "NID তে আমার নাম ভুল আছে, কীভাবে ঠিক করব?"

**Output:** A structured, step-by-step answer containing:
1. Correct service name and responsible ministry/office
2. Required documents (checklist format)
3. Fees (with a "last verified" date)
4. Step-by-step process
5. A scam warning specific to that service, if applicable

---

## 2. High-Level Architecture

This is a **multi-agent system orchestrated with LangGraph**, backed by a
**RAG (Retrieval-Augmented Generation) pipeline** over scraped government
documentation.

```
User Query (Bengali/English)
        |
        v
[1. Intent Classifier Agent] -----> classifies into one of ~15-20 service categories
        |
        v
[2. Retrieval Agent] -------------> queries vector DB filtered by service category
        |
        v
[3. Freshness/Verification Agent] -> checks last_updated metadata, flags staleness
        |
        v
[4. Scam-Pattern Agent] ----------> looks up curated scam-pattern table for this service
        |
        v
[5. Response Composer Agent] -----> assembles final answer in checklist format
        |
        v
Final Answer to User
```

### Agent responsibilities

| Agent | Job | Notes |
|---|---|---|
| Intent Classifier | Map free-text query to a fixed taxonomy of government services | Small, fast LLM call. Fixed taxonomy prevents drift/hallucination of service categories. |
| Retrieval Agent | Vector search over indexed government docs, filtered by classified category | Uses multilingual embeddings since queries mix Bengali/English. |
| Freshness/Verification Agent | Checks `last_scraped_date` metadata on retrieved chunks | If data is older than a threshold (e.g. 90 days), append a disclaimer telling the user to verify at the source. |
| Scam-Pattern Agent | Cross-references service category against a hardcoded, human-verified table of known scam patterns | **Do NOT let the LLM generate scam warnings freely** — hallucinated scam claims could mislead users or defame legitimate offices. Only use verified, sourced entries. |
| Response Composer | Merges all of the above into one clear, step-by-step response | Should always cite the source URL and last-verified date. |

---

## 3. Data Sources

### Primary (official government sources — highest trust)
- `bangladesh.gov.bd` — National Web Portal, links to every ministry/department
- `epassport.gov.bd` — passport application process, fees, forms
- `nidw.gov.bd` — Election Commission NID services
- `land.gov.bd` — Ministry of Land portal (khatian, mutation/namjari, land tax)
- `etaxnbr.gov.bd` — NBR e-TIN and tax filing
- `bsp.brta.gov.bd` — BRTA driving license, vehicle registration
- District e-Mutation / e-Porcha portals
- Union Digital Centre / Upazila e-service portals — birth/death registration
- City Corporation sites (e.g. `dncc.gov.bd`, `dscc.gov.bd`) — trade license

### Secondary (for scam pattern data only — never for factual procedure data)
- News archives: Prothom Alo, The Daily Star — search "দালাল" (dalal) + service name
- RTI (Right to Information) published responses
- Community reports (Facebook groups, r/bangladesh) — **must be manually
  verified before inclusion**; never auto-ingest these into the RAG index as
  factual content

### Data schema (after scraping/normalization)

```json
{
  "service_name": "Passport Renewal (e-Passport)",
  "ministry": "Department of Immigration and Passports",
  "category": "passport",
  "required_docs": ["Old passport", "NID", "Passport fee payment slip", "..."],
  "fees": {
    "regular_48_page_5yr": "BDT 4025",
    "express_48_page_5yr": "BDT 6325"
  },
  "steps": ["Fill online application at epassport.gov.bd", "..."],
  "office_location": "Regional Passport Office (varies by district)",
  "last_scraped_date": "2026-09-01",
  "source_url": "https://www.epassport.gov.bd/...",
  "scam_warnings": [
    "Never pay 'extra fees' to individuals claiming to expedite outside official channels"
  ]
}
```

---

## 4. Build Plan (Phased)

### Phase 1 — Data Collection & Preprocessing
- Write scrapers (Playwright recommended) for each official portal
- Normalize into the JSON schema above
- Manually verify a sample against real-world experience/news — government
  fee data especially tends to be outdated on official sites

### Phase 2 — RAG Pipeline
- Chunk by **service**, not by raw page, to avoid mixing unrelated procedures
- Embed using a multilingual model (e.g. `BAAI/bge-m3` or
  `intfloat/multilingual-e5-large`) to handle mixed Bengali/English queries
- Store in FAISS (or any vector DB) with metadata filters: `category`,
  `ministry`, `last_scraped_date`

### Phase 3 — Agent Orchestration (LangGraph)
- Build Intent Classifier node (fixed taxonomy, ~15-20 categories)
- Build Retrieval node (vector search filtered by classified category)
- Build Scam-Pattern node (lookup table, NOT LLM-generated)
- Chain: `classify -> retrieve -> verify_freshness -> check_scams -> compose`

### Phase 4 — Interface
- Bengali-first chat UI (Gradio or React)
- "Report incorrect info" feedback button — crowdsourced correction loop,
  since government data drifts over time

### Phase 5 — Evaluation
- Build a test set of ~50 real questions across service categories
- Manually verify agent answers against actual current requirements
  (call the office directly, check recent community reports)
- Track: retrieval accuracy, and especially **hallucination rate on
  fees/required documents** — incorrect fee/document info is worse than no
  answer at all

---

## 5. Critical Design Constraints (read before extending this project)

1. **Never let the LLM freely generate fees, document lists, or scam
   warnings from its own knowledge.** All factual claims must come from the
   RAG-retrieved, human-verified data. Bangladeshi government fee schedules
   change and LLM training data goes stale — an ungrounded guess here can
   cost a real user money or a wasted trip.
2. **Always surface `last_scraped_date` and `source_url` to the user.** This
   lets them verify before acting, which matters given how often these
   change.
3. **Scam-pattern warnings must be curated and sourced, not generated.**
   Treat this table like a moderated wiki, not free LLM output.
4. **Support code-mixed Bengali/English queries** — real users rarely type
   in pure Bengali or pure English.
5. **Re-scrape periodically** (e.g. monthly) and diff against the previous
   version to catch fee/process changes automatically.

---

## 6. Tech Stack Summary

- **Scraping:** Playwright + BeautifulSoup
- **Embeddings:** Multilingual sentence embedding model (bge-m3 or similar)
- **Vector store:** FAISS
- **Orchestration:** LangGraph + LangChain
- **LLM:** Any capable instruction-tuned model (GPT-4-class or open model via
  Unsloth for a fine-tuned smaller model, if cost is a concern)
- **Frontend:** Gradio (fast prototype) or React + Flask/FastAPI (production)

---

## 7. Suggested Repo Structure

```
gov-service-agent/
├── explain.md                 <- this file
├── scrapers/
│   ├── epassport_scraper.py
│   ├── nid_scraper.py
│   ├── land_scraper.py
│   └── ...
├── data/
│   └── services/               <- normalized JSON per service
├── rag/
│   ├── chunker.py
│   ├── embed_and_index.py
│   └── retriever.py
├── agents/
│   ├── intent_classifier.py
│   ├── retrieval_agent.py
│   ├── freshness_agent.py
│   ├── scam_pattern_agent.py
│   ├── scam_patterns.json      <- curated, sourced scam pattern table
│   └── response_composer.py
├── graph.py                    <- LangGraph state graph wiring all agents
├── app.py                      <- Gradio/Flask frontend entry point
└── eval/
    ├── test_questions.json
    └── evaluate.py
```
