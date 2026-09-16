# 🇧🇩 Government Service Navigation Agent (GSNA)

**সরকারি সেবা সহায়ক**: an AI assistant that helps Bangladeshi citizens find out
**which government service they need, which documents to bring, what it costs, and
how to avoid middleman ("dalal") scams**. You can ask in Bengali, English or Banglish.

> Every answer shows its official source and the date that source was last updated.
> If the system has no verified information, it says so instead of guessing.

---

## Table of contents

- [Why this project exists](#why-this-project-exists)
- [What it can answer](#what-it-can-answer)
- [Example](#example)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Usage](#usage)
- [Evaluation](#evaluation)
- [Safety principles](#safety-principles)
- [Data availability](#data-availability)
- [Author](#author)

---

## Why this project exists

Information about government services in Bangladesh (passport, NID, land records,
driving license, TIN and more) is scattered across many portals. It is often out of
date or only available in scanned PDFs. People without prior experience go to the
wrong office, bring the wrong papers or pay middlemen for help they don't need.

GSNA collects this information from **official sources only**, organizes it into
structured records and answers everyday questions in plain language.

---

## What it can answer

A user types a question the way they normally would:

| Language | Example question |
|---|---|
| Bengali | `আমার জমির খতিয়ান দরকার, কী করতে হবে?` |
| English | `How do I renew my passport and how much does it cost?` |
| Banglish | `jonmo nibondhon korte koto taka lage` |
| Mixed | `NID তে আমার নাম ভুল আছে, কীভাবে ঠিক করব?` |

The answer includes:

1. ✅ The correct service and the office responsible for it
2. 📄 A checklist of required documents
3. 💰 Fees, each with its source and "last updated" date
4. 🪜 Step-by-step process
5. 🛡️ Scam warnings specific to that service (from a hand-checked list)

The reply comes back in the language of the question. Banglish questions get Bengali answers.

**Service categories:** passport, new NID, NID correction, birth registration, death
registration, land record (khatian), land mutation, land tax, driving license, vehicle
registration, TIN registration, income tax return, VAT registration, trade license,
company registration, police clearance, citizenship certificate, marriage certificate.

---

## Example

**Question:**

```
How much does a new passport cost?
```

**Pipeline trace** (how the answer was produced):

```
[classify -> passport (alias, 1.000)]
[retrieve -> 5 chunks, record=yes]
[freshness -> stale]
[scams -> 1 curated entry]
[compose -> 5197 chars]
```

**Answer (shortened):**

```markdown
## ইলেকট্রনিক (E-Passport) পাসপোর্ট ইস্যু
**Office:** ইমিগ্রেশন ও পাসপোর্ট অধিদপ্তর (Department of Immigration and Passports)

> ⚠️ Verify before you act.
> - The source page was last updated 2026-05-11 (128 days ago).
> - Always confirm at the source: https://dip.gov.bd/...

### 🪜 Process
1. Submit the application online, or offline on the printed PDF form.
2. Pay the passport fee and obtain the A-Challan copy.
3. Attend in person at the Divisional / Regional Passport Office with your original NID/BRC.

### 💰 Fees
| Service                                        | Fee (BDT)     | Source last updated |
|------------------------------------------------|---------------|---------------------|
| 48-page, 5-year validity, Regular (21 days)    | ৪,০২৫ / 4,025 | 2026-05-11          |
| 48-page, 10-year validity, Express (10 days)   | ৮,০৫০ / 8,050 | 2026-05-11          |
| 64-page, 10-year validity, Super Express (2 d) | ১৩,৮০০ / 13,800 | 2026-05-11        |

### 🛡️ Know this before anyone offers to 'help'
- If a passport office does not resolve your issue, there is a free official
  escalation chain (Grievance Redress Officer → Appeal Officer → Cabinet Division).
  Paying an intermediary to "push" a file is never the only option.
```

---

## How it works

The core is a **LangGraph** pipeline of five small agents. Each agent does one job,
so every fact in an answer can be traced back to the agent that produced it.

```
                 ┌────────────────────┐
  user query ──▶ │ 1. Intent classify │── unknown / out of scope ──┐
                 └─────────┬──────────┘                            │
                           ▼                                       │
                 ┌────────────────────┐                            │
                 │ 2. Retrieve (RAG)  │  FAISS search, filtered by │
                 └─────────┬──────────┘  service category          │
                           ▼                                       │
                 ┌────────────────────┐                            │
                 │ 3. Freshness check │  how old is the source?    │
                 └─────────┬──────────┘                            │
                           ▼                                       │
                 ┌────────────────────┐                            │
                 │ 4. Scam lookup     │  hand-checked table only   │
                 └─────────┬──────────┘                            │
                           ▼                                       │
                 ┌────────────────────┐ ◀──────────────────────────┘
                 │ 5. Compose answer  │  template, or LLM + validation
                 └─────────┬──────────┘
                           ▼
                        answer
```

| # | Agent | File | What it does |
|---|---|---|---|
| 1 | Intent classifier | `agents/intent_classifier.py` | Matches the question to one fixed service category, first by alias ("khatian", "e-TIN") and then by multilingual embeddings. Returns `unknown_service` when confidence is low instead of guessing. |
| 2 | Retrieval agent | `agents/retrieval_agent.py` | Searches the FAISS index only within the chosen category, so a passport question never pulls in land-office text. |
| 3 | Freshness agent | `agents/freshness_agent.py` | Judges age by the date the page says it was updated, not the date it was scraped. Shows a warning if the source is stale. |
| 4 | Scam pattern agent | `agents/scam_pattern_agent.py` | Looks up hand-checked, sourced warnings in `agents/scam_patterns.json`. It never generates text. |
| 5 | Response composer | `agents/response_composer.py`, `agents/llm_composer.py` | Builds the answer from verified data. The optional LLM layer (Groq) writes a shorter, more focused reply, and every number it outputs is checked against the record. |

### Data ingestion

Answers are built from structured **service records** that follow
`schema/service_record.schema.json`. These records are produced by:

- **`scrapers/v2ministry.py`**: one configurable scraper for the government CMS
  used by many ministries (DIP, BRTA, land offices, city corporations…).
- **`tools/`**: helpers for polite, cached fetching, decoding broken Bengali PDFs
  (bad ToUnicode maps, legacy Bijoy/SutonnyMJ encoding), OCR, staleness detection
  and record validation.
- **`agents/ingestion_agent.py`**: a tool-using agent that looks for missing
  categories. It can only save **drafts** marked `unverified`, and a human has to
  review them before they are used.

---

## Project structure

```
GSNA/
├── app.py                  # Gradio web UI (Bengali-first) + "report incorrect info"
├── graph.py                # LangGraph pipeline; also a CLI entry point
├── agents/                 # The five pipeline agents + ingestion agent
│   ├── intent_classifier.py
│   ├── retrieval_agent.py
│   ├── freshness_agent.py
│   ├── scam_pattern_agent.py
│   ├── scam_patterns.json  # Hand-checked scam warnings with sources
│   ├── response_composer.py
│   ├── llm_composer.py
│   ├── ingestion_agent.py
│   └── agent_tools.py
├── rag/                    # Chunking, embedding (multilingual-e5) and FAISS search
├── scrapers/               # V2Ministry CMS scraper + per-office config
├── tools/                  # Fetching, PDF/Bengali decoding, OCR, validation
├── schema/                 # JSON schema for a service record
├── eval/                   # Evaluation script + test questions
├── .env.example            # Environment variable template
└── data/                   # (not included in this repository, see below)
```

---

## Getting started

### Requirements

- Python **3.10+** (developed on 3.12)
- About 1 GB of disk space for the embedding model
- Optional: a [Groq](https://console.groq.com/) API key for the LLM answer layer

### 1. Clone the repository

```bash
git clone https://github.com/Sakib9797/Government-Service-Navigation-Agent.git
cd Government-Service-Navigation-Agent
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install langgraph gradio sentence-transformers faiss-cpu numpy groq python-dotenv jsonschema pdfminer.six pymupdf fonttools
```

Optional, only needed for OCR of scanned PDFs:

```bash
pip install easyocr
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set the values you need:

```env
GROQ_API_KEY=gsk_your_key_here   # optional, for LLM-written answers
GSNA_LLM_COMPOSER=1              # set to 0 to use template answers only
HF_HUB_OFFLINE=1                 # set to 0 on first run so the model can download
```

> Without a Groq key the system still works fully. It uses the template composer.

### 5. Build the search index

```bash
python rag/embed_and_index.py
```

This embeds the service records and writes `rag/index/chunks.faiss`.

---

## Usage

### Web app

```bash
python app.py
```

Open **http://127.0.0.1:7860** in your browser, type a question or click an example.
You can expand **"Pipeline trace"** to see how the answer was produced, and
**"Report incorrect information"** to flag a mistake for human review.

### Command line

```bash
python graph.py "TIN khulte koto taka lage"
```

```bash
python graph.py "How do I renew my passport and how much does it cost?"
```

> On Windows, run `$env:PYTHONIOENCODING="utf-8"` first so Bengali text prints correctly.

### Validate records

```bash
python tools/validate_taxonomy.py
```

```bash
python tools/validate_records.py
```

### Run the ingestion agent for a missing category

```bash
python agents/ingestion_agent.py land_tax
```

```bash
python agents/ingestion_agent.py land_tax --brain=groq
```

### Check sources for changes

```bash
python tools/rescrape.py
```

This reports fee or date changes on source pages. It never updates records
automatically.

---

## Evaluation

```bash
python eval/evaluate.py
```

The evaluation reports four separate scores:

| Score | What it checks |
|---|---|
| **Intent** | Was the question matched to the correct service category? |
| **Assertions** | Does each answer contain (or avoid) the expected content? |
| **Grounding** ⛔ | Every fee and document in an answer must exist exactly in the service record. Anything else counts as a hallucination. |
| **Safety** ⛔ | Every answer shows its source, and an unverified record never shows a fee table or checklist. |

**Grounding** and **Safety** are hard gates. A change that makes either one worse should not ship.

---

## Safety principles

- **No invented numbers.** Fees are read directly from verified records, never from
  model output or embedding search.
- **Saying "I don't know" is fine.** If a fee isn't published, the answer says
  *not verified* rather than guessing.
- **Date by content.** Freshness uses the page's own "last updated" date.
- **Scam warnings are hand-checked.** They are never written by a model.
- **People review changes.** Agent drafts, re-scrape results and user reports all
  need human approval before they reach users.
- **Polite scraping.** At least 6 seconds between requests per host, back-off on 429/503,
  and every response is cached.
- **Privacy.** Gradio telemetry is disabled, and the app runs locally by default.

---

## Data availability

The `data/` directory (service records, taxonomy, source audit, PDF index and cached
pages) is **not included** in this repository. To run the project you need to
supply your own `data/` directory:

```
data/
├── taxonomy.json            # service categories and aliases
├── services/<category>.json # records following schema/service_record.schema.json
├── source_candidates.json   # official URLs to audit
├── source_audit.json        # output of tools/audit_sources.py
└── pdf_index.json           # catalogue of government PDFs
```

Records can be rebuilt with the tools in `tools/` and `scrapers/`, starting from
`python tools/audit_sources.py`.

---

## Author

**Sakib Raihan** ([@Sakib9797](https://github.com/Sakib9797))

> ⚠️ **Disclaimer:** GSNA is an informational tool, not an official government service.
> Government fees and procedures change, so always confirm with the official source
> linked in each answer before you pay or apply.
