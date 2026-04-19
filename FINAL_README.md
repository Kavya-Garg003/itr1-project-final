# ITR-1 RAG Agent — Complete Project Documentation

**What it is:** An AI-powered system that reads your tax documents (Form 16, bank statements), automatically fills every field of the ITR-1 Sahaj form, compares old vs new tax regime and recommends the better one, validates the filled form for errors, explains every filled field in plain English, and lets you ask questions about your taxes through a chat interface grounded in official CBDT sources.

**Who it is for:** Any salaried individual filing ITR-1 for AY 2024-25 with income up to ₹50 lakh from salary, one house property, and other sources (interest income).

---

## Table of Contents

1. [How the whole system works — user flow](#1-how-the-whole-system-works)
2. [Architecture — all services](#2-architecture)
3. [Complete file structure with descriptions](#3-complete-file-structure)
4. [The RAG knowledge base — what goes into it](#4-the-rag-knowledge-base)
5. [The agent pipeline — LangGraph step by step](#5-the-agent-pipeline)
6. [The document parsers](#6-the-document-parsers)
7. [Setup — exact steps to run](#7-setup-exact-steps)
8. [What you need to provide](#8-what-you-need-to-provide)
9. [Limitations — what it does and does not do](#9-limitations)
10. [Interview cheat sheet](#10-interview-cheat-sheet)

---

## 1. How the whole system works

Here is the complete user flow from opening the browser to getting a filled ITR-1:

**Step 1 — Upload documents.** The user goes to `http://localhost:3000/upload` and drags in their Form 16 PDF and bank statement PDFs. The frontend sends these to the API gateway at port 3001, which forwards them to the Doc Parser service at port 8002.

**Step 2 — Document parsing.** The Doc Parser reads each PDF using pdfplumber. For Form 16, it extracts gross salary, HRA exemption, standard deduction, professional tax, every deduction claimed (80C, 80D, 80CCD), and total TDS deducted. For bank statements it finds the transaction table, classifies each row as salary/savings interest/FD interest/TDS, and totals them up. For AIS/Form 26AS it cross-checks TDS credits and flags any discrepancy between what was deducted and what was actually deposited with the government. Each parser returns a structured JSON object.

**Step 3 — Agent pipeline.** The parsed documents are sent to the Agent Orchestrator at port 8000, which runs a 5-node LangGraph pipeline:

- **fill_form node** — maps every extracted field to the correct ITR-1 field path defined in `shared/itr1_schema.py`. Assigns a confidence score (0–1) and source citation to every field. Fields that came from a document get high confidence; fields that had to be inferred get lower confidence and are flagged for manual review.
- **compare_regimes node** — runs the actual AY 2024-25 slab math for both old and new regime on the user's income and deductions. Does not use an LLM for this calculation — it uses the `compute_tax()` function in `shared/tax_utils.py` which has the exact statutory slab rates and is tested. Picks the regime with lower tax and records the saving.
- **validate node** — checks 12 rules: 80C family cap at ₹1.5L, HRA and 80GG not both claimed, income not exceeding ₹50L (ITR-1 limit), 80TTA and 80TTB not both claimed, TDS cross-check against expected tax, etc. Each violation becomes a flag with severity (error/warning/info) and a plain-English fix suggestion.
- **score_confidence node** — aggregates confidence across all filled fields. Any field that was not found in the uploaded documents gets confidence 0.3 and is automatically flagged for manual review.
- **explain node** — generates plain-English explanations for complex fields (HRA calculation, 87A rebate eligibility, regime recommendation reasoning) using GPT-4o-mini.

**Step 4 — Form viewer.** The filled form is shown at `/form?session=SESSION_ID`. Every field shows its value, a colour-coded confidence bar (green ≥ 80%, amber ≥ 50%, red below), and the source badge (Form 16 / Bank stmt / Computed / Manual). Validation flags appear as banners at the top. The user can click the edit button on any field, correct the value, and save — which sets that field's confidence to 100% (human verified) and logs it in the audit trail.

**Step 5 — Chat.** The user can go to `/chat?session=SESSION_ID` and ask any tax question in natural language. The question goes to the RAG service at port 8001, which embeds it, retrieves the 5 most relevant chunks from the FAISS vector store using MMR diversity filtering, reranks them with a cross-encoder, and sends them with the question to GPT-4o-mini. The answer is returned with source citations linking back to the exact CBDT page or document. The chat is aware of the user's filled form if they are in a session (it knows their income, regime, and taxable income).

**Step 6 — Export.** The user clicks "Export JSON" to download the completely filled ITR-1 as a JSON file, which can be imported into the ITD offline utility or used to pre-fill the online portal.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend  Next.js · React · Tailwind  :3000                │
│  /upload   /form?session=...   /chat?session=...            │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────────┐
│  API Gateway  Node.js / Express  :3001                      │
│  Auth · Rate limiting · File proxying · Service routing     │
└────────┬──────────────────┬─────────────────┬──────────────┘
         │                  │                 │
┌────────▼────┐  ┌──────────▼──────┐  ┌──────▼─────────────┐
│ Doc Parser  │  │  RAG Service    │  │ Agent Orchestrator  │
│ Python/     │  │  Python/FastAPI │  │ Python/FastAPI      │
│ FastAPI     │  │  :8001          │  │ :8000               │
│ :8002       │  │                 │  │                     │
│             │  │  FAISS index    │  │  LangGraph pipeline │
│ form16.py   │  │  MMR retrieval  │  │  5 nodes:           │
│ bank_stmt   │  │  cross-encoder  │  │  fill_form          │
│ ais.py      │  │  GPT-4o-mini    │  │  compare_regimes    │
└────────┬────┘  └──────────┬──────┘  │  validate           │
         │                  │         │  score_confidence   │
         │                  │         │  explain            │
         └──────────────────┴─────────┴──────────────────┐  │
                                                          │  │
┌─────────────────────────────────────────────────────────▼──▼──┐
│  Shared Python  (imported by all 3 Python services)           │
│  shared/itr1_schema.py   — Pydantic model for every ITR-1 field│
│  shared/tax_utils.py     — Slab rates, HRA, 87A, regime math  │
└───────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Infrastructure                                         │
│  PostgreSQL :5432  · Redis :6379                        │
│  Docker Compose ties everything together                │
└─────────────────────────────────────────────────────────┘
```

**Why microservices:**
- Each service scales differently. Doc Parser runs only on document upload. RAG runs on every chat query. Agent runs on pipeline trigger.
- Python for ML (pdfplumber, FAISS, LangChain, sentence-transformers). Node.js for async I/O coordination.
- AY updates only redeploy the RAG service — no other service touched.

---

## 3. Complete file structure

Every file in the project, what it does, and why it exists.

```
itr1-rag-agent/
│
├── .env.example                 Configuration template. Copy to .env and fill in.
├── docker-compose.yml           Starts all 7 services in correct order with health checks.
├── pytest.ini                   Tells pytest where tests live and default flags.
│
├── knowledge-base/              Everything needed to build the FAISS vector store.
│   ├── requirements.txt         Packages for running kb scripts locally (pdfplumber, faiss, etc)
│   ├── scraper.py               Scrapes 5 websites using headless Playwright + BS4. Outputs
│   │                            markdown chunks to rag_output/chunks/. Handles JS-heavy sites
│   │                            (ClearTax is React, incometax.gov.in is Drupal).
│   ├── embedder.py              Takes all_chunks.jsonl → embeds → saves FAISS index.
│   │                            Two backends: HuggingFace BGE (free) or OpenAI (better quality).
│   │                            Saves: vector_store/AY2024-25.faiss + AY2024-25.meta.json
│   ├── retriever.py             Standalone retriever class: MMR + cross-encoder reranking.
│   │                            Importable into any Python service. Also has a CLI for testing.
│   ├── manual_fallback.py       Fallback scraper using curl when Playwright gets blocked.
│   │                            Also handles manually saved HTML files from browser.
│   ├── pdf_ingester.py          Reads your downloaded PDFs from knowledge-base/pdfs/.
│   │                            Extracts text (pdfplumber + PyMuPDF), cleans, chunks at
│   │                            512 tokens, writes to rag_output/chunks/. Run AFTER scraper.py,
│   │                            then run embedder.py to include PDFs in FAISS.
│   ├── itr_form_schema_loader.py Reads the official ITR-1 JSON schema + Excel field map you
│   │                            downloaded from the ITD utility. Maps every official field name
│   │                            to our itr1_schema.py dot-path. Outputs field_map.json.
│   ├── pdfs/                    PUT YOUR DOWNLOADED PDFS HERE.
│   │   ├── itr1_instructions_AY2024-25.pdf
│   │   ├── circular_03_2025.pdf
│   │   ├── income_tax_act_sections.pdf
│   │   └── ... (any other PDFs)
│   └── form_files/              PUT YOUR DOWNLOADED FORM FILES HERE.
│       ├── itr1_schema_AY2024-25.json   (JSON schema from ITD utility)
│       └── itr1_fields_AY2024-25.xlsx  (Excel field map)
│
├── shared/                      Python package imported by all 3 Python services.
│   ├── __init__.py
│   ├── itr1_schema.py           BACKBONE OF THE ENTIRE PROJECT. Pydantic models for:
│   │                            PersonalInfo, SalaryIncome (Schedule S), HousePropertyIncome
│   │                            (Schedule HP), OtherSourcesIncome (Schedule OS), Deductions
│   │                            (Chapter VI-A with all sections), TDSEntry (Schedule TDS1),
│   │                            TaxComputation, FieldConfidence, ValidationFlag, ITR1Form.
│   │                            Every Python service imports from here. No field defined
│   │                            anywhere else.
│   └── tax_utils.py             All statutory tax math for AY 2024-25. Contains:
│                                - AY_CONFIG dict with exact slab rates, rebate limits, cess rate,
│                                  surcharge slabs for both regimes
│                                - compute_tax() — progressive slab calculation
│                                - compare_regimes() — full old vs new comparison with rupee saving
│                                - compute_hra_exemption() — 3-component HRA minimum
│                                - enforce_deduction_limits() — applies all statutory caps
│                                All functions are pure Python, no LLM, deterministic, tested.
│
├── doc-parser/                  Python microservice. Reads PDFs, returns structured JSON.
│   ├── __init__.py
│   ├── Dockerfile
│   ├── requirements.txt         pdfplumber, fastapi, uvicorn, python-multipart, pillow
│   ├── main.py                  FastAPI app. Endpoints:
│   │                            POST /parse/form16       — Form 16 PDF
│   │                            POST /parse/bank-statement — Bank statement PDF
│   │                            POST /parse/auto         — auto-detect document type
│   │                            POST /parse/ais          — AIS / Form 26AS PDF
│   │                            GET  /health
│   └── parsers/
│       ├── __init__.py
│       ├── form16.py            Form 16 parser. Uses regex patterns matching TRACES standard
│       │                        format (the format CBDT mandates all employers use). Extracts:
│       │                        employer TAN/PAN, employee PAN, assessment year, gross salary,
│       │                        Sec 17(1)/(2)/(3) breakdown, all Sec 10 exempt allowances
│       │                        (HRA 10(13A), LTA 10(10)), Sec 16 deductions (standard, prof tax),
│       │                        all Chapter VI-A deductions claimed, TDS by quarter, rebate 87A.
│       │                        Falls back to pdfplumber table extraction if regex misses fields.
│       │                        Returns parse_confidence (0–1) and warnings list.
│       ├── bank_statement.py    Bank statement parser. Detects bank by header patterns (SBI,
│       │                        HDFC, ICICI, Axis). Finds transaction table via pdfplumber.
│       │                        Classifies each row: salary / interest_savings / interest_fd /
│       │                        interest_rd / tax_deducted / other. Aggregates by category.
│       │                        Savings interest → 80TTA. FD interest → other sources income.
│       │                        Bank TDS → Schedule TDS2. Returns totals + transaction list.
│       └── ais.py               AIS / Form 26AS parser. Reads TDS credit table by deductor.
│                                Separates Sec 192 (salary TDS) from Sec 194A (interest TDS).
│                                Flags discrepancies where tax deducted ≠ tax deposited.
│                                reconcile_form16_vs_ais() cross-checks Form 16 TDS vs AIS TDS
│                                and returns a mismatch report used by the validator.
│
├── rag-service/                 Python microservice. Answers tax questions using FAISS + LLM.
│   ├── __init__.py
│   ├── Dockerfile
│   ├── requirements.txt         fastapi, sentence-transformers, faiss-cpu, openai
│   └── main.py                  FastAPI app. Endpoints:
│                                POST /query  — full RAG pipeline: embed → MMR → rerank → LLM
│                                POST /query/chunks — return raw chunks without LLM (debug)
│                                GET  /indexes — list available AY namespaces
│                                GET  /health
│                                Loads FAISS index from vector_store/AY2024-25.faiss on startup.
│                                Uses sentence-transformers BGE model to embed queries (same
│                                model used by embedder.py — MUST match). MMR retrieval with
│                                lambda=0.6, cross-encoder reranking with ms-marco-MiniLM.
│                                GPT-4o-mini generates the final answer from retrieved context.
│
├── agent-orchestrator/          Python microservice. Runs the LangGraph ITR-1 pipeline.
│   ├── __init__.py
│   ├── Dockerfile
│   ├── requirements.txt         fastapi, langgraph, langchain, langchain-openai, httpx
│   ├── main.py                  FastAPI app. Endpoints:
│   │                            POST /pipeline/run    — run full 5-node pipeline
│   │                            GET  /pipeline/session/{id} — get filled form for session
│   │                            POST /pipeline/update-field — manual field correction
│   │                            POST /chat/query      — Q&A (proxies to RAG service)
│   │                            GET  /pipeline/export/{id} — download filled form JSON
│   │                            GET  /health
│   │                            Sessions stored in-memory dict (replace with Redis in prod).
│   └── graph/
│       ├── __init__.py
│       └── itr_graph.py         THE HEART OF THE PROJECT. LangGraph state machine with 5 nodes.
│                                AgentState TypedDict holds everything across nodes.
│                                node_fill_form: maps parsed docs → ITR-1 fields, assigns
│                                  confidence scores, creates audit trail entries.
│                                node_compare_regimes: calls compare_regimes() from tax_utils,
│                                  fills tax_computation section, records regime recommendation.
│                                node_validate: 12 validation checks, creates ValidationFlag
│                                  objects with severity and fix suggestion for each issue.
│                                node_score_confidence: ensures critical fields have scores,
│                                  marks missing fields as flagged.
│                                node_explain: GPT-4o-mini generates plain-English explanation
│                                  for HRA exemption, 87A rebate, regime recommendation.
│                                run_itr_pipeline(): convenience function that builds and
│                                  invokes the compiled graph with an initial state.
│
├── api-gateway/                 Node.js microservice. The single entry point for the frontend.
│   ├── Dockerfile
│   ├── package.json             express, multer, cors, express-rate-limit, jsonwebtoken, node-fetch
│   └── src/
│       └── index.js             Express app. Routes:
│                                POST /api/upload/:docType → doc-parser (multipart/form-data proxy)
│                                POST /api/pipeline/run  → agent-orchestrator
│                                GET  /api/pipeline/:id  → agent-orchestrator
│                                POST /api/pipeline/update-field → agent-orchestrator
│                                GET  /api/pipeline/export/:id  → agent-orchestrator
│                                POST /api/chat           → agent-orchestrator → rag-service
│                                GET  /api/health         → aggregates all service health checks
│                                Multer handles file uploads in-memory (max 20MB, PDF/JPG/PNG).
│                                JWT auth middleware (SKIP_AUTH=true for local dev).
│                                Rate limiting: 100 req/15min general, 20 req/15min for uploads.
│
├── frontend/                    Next.js 14 / React / Tailwind. Three pages.
│   ├── Dockerfile               Multi-stage: build → standalone output
│   ├── package.json             next, react, tailwindcss, typescript
│   ├── next.config.js           output: standalone (for Docker)
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   └── src/app/
│       ├── layout.tsx           Root layout wrapping all pages. Sets page title and metadata.
│       ├── page.tsx             Root route — immediately redirects to /upload.
│       ├── globals.css          Tailwind base imports + body font.
│       ├── upload/
│       │   └── page.tsx         Document upload UI. Two DropZone components (Form 16 + bank
│       │                        statements). Each drop zone calls /api/upload/:docType, shows
│       │                        parse confidence and warnings on the returned FileCard.
│       │                        "Fill My ITR-1" button calls /api/pipeline/run with all parsed
│       │                        docs, then navigates to /form?session=SESSION_ID.
│       ├── form/
│       │   └── page.tsx         Filled form viewer. Loads session from /api/pipeline/:id.
│       │                        Shows every ITR-1 field grouped into section cards
│       │                        (Salary, HP, Other Sources, Deductions, Tax Computation).
│       │                        Each FieldRow shows: label, explanation, confidence bar, source
│       │                        badge, value, edit button. Validation flags at top as banners.
│       │                        Regime recommendation card in green. EditModal for any field
│       │                        (calls /api/pipeline/update-field). Wrapped in Suspense.
│       └── chat/
│           └── page.tsx         Q&A chat interface. Calls /api/chat with the question.
│                                Shows RegimeCard (old vs new tax + saving) if session active.
│                                8 suggested questions shown before first message.
│                                Answers show with source citation links. Auto-scroll.
│                                Shift+Enter for newline, Enter to send. Wrapped in Suspense.
│
└── tests/                       Pytest test suite.
    ├── __init__.py
    ├── conftest.py              Shared fixtures: sample Form 16 data, sample bank data.
    │                            Adds all service directories to sys.path.
    ├── test_tax_logic.py        38 tests for shared/tax_utils.py and shared/itr1_schema.py:
    │                            - Tax slab computation (both regimes)
    │                            - 87A rebate boundary conditions (exactly ₹7L, ₹7L+₹1)
    │                            - Cess calculation (exactly 4%)
    │                            - New regime slab correctness (₹90,000 at ₹12L income)
    │                            - Old regime slab correctness (₹1,12,500 at ₹10L income)
    │                            - Surcharge trigger at ₹50L
    │                            - Regime comparison (when old is better, when new is better)
    │                            - Refund computation
    │                            - HRA 3-component minimum (metro/non-metro, zero rent, etc.)
    │                            - Deduction caps (80C ₹1.5L, 80CCD(1B) ₹50k, 80TTA ₹10k)
    │                            - HP interest cap at ₹2L for self-occupied
    │                            - New regime deductions zeroed correctly
    │                            All 38 pass.
    └── test_pipeline.py         Pipeline node tests (mocked LLM for explain node):
                                 - Each LangGraph node tested in isolation
                                 - fill_form: gross salary, PAN, taxable salary, bank interest,
                                   80TTA, confidence scores, audit trail, TDS entry
                                 - compare_regimes: both taxes computed, recommended is lower
                                 - validate: no errors for valid input, flags missing Form 16,
                                   flags income > ₹50L
                                 - score_confidence: critical fields scored, missing fields flagged
                                 - Full integration test with mocked GPT
```

---

## 4. The RAG knowledge base

### What goes in

The FAISS vector store contains two types of content:

**1. Web content (from scraper.py)**

| URL | What it contains | Why it matters for RAG |
|-----|-----------------|------------------------|
| incometax.gov.in/help/how-to-file-itr1-form-sahaj | Step-by-step ITR-1 filing guide | Field-level explanations for every section |
| incometax.gov.in/help/e-filing-itr1-form-sahaj-faq | Official FAQs on eligibility, deductions, regime | Ideal Q&A chunks |
| incometax.gov.in/help/individual/return-applicable-1 | Slab tables, surcharge rules, 87A rebate numbers | Exact numbers for regime comparison |
| cleartax.in/s/80c-80-deductions | Plain-English 80C guide | Edge case coverage |
| cleartax.in/s/itr1 | Complete ITR-1 guide | Broader coverage |

**2. PDF content (from pdf_ingester.py)**

Your downloaded PDFs go in `knowledge-base/pdfs/`. The ingester auto-detects what each PDF is based on the filename using regex patterns. Recommended files:

```
itr1_instructions_AY2024-25.pdf   ← CBDT instructions booklet (most important)
circular_03_2025.pdf               ← CBDT Circular 03/2025 (TDS on salary FY 2024-25)
income_tax_act_sections.pdf        ← IT Act: Sec 80C, 80D, 87A, 115BAC, 139(1), etc.
finance_act_2023.pdf               ← Budget 2023 changes
```

**3. Official form files (from itr_form_schema_loader.py)**

Your downloaded ITR-1 JSON schema and Excel field map go in `knowledge-base/form_files/`. The loader builds `field_map.json` which maps every official ITD field name (e.g. `Section80C`) to the schema path (e.g. `deductions.sec_80c`).

### How chunks are created

Chunking strategy (512 tokens, 64-token overlap):
- FAQ pages: split on Q&A pairs — each Q+A is one self-contained chunk
- User manuals: split on markdown headings — each section is one chunk
- PDFs: split on numbered section headings (e.g. "2.1", "PART A") — then slide a window if any section exceeds 512 tokens

Every chunk carries metadata: `source`, `doc_type`, `applicable_ay`, `section`, `url`. This metadata is stored alongside every FAISS vector so every retrieval result can cite its exact source.

### How retrieval works

1. User's question is embedded with the same model used to build the index (BGE-small-en)
2. FAISS flat-L2 search returns top-15 candidates
3. MMR (Maximum Marginal Relevance, λ=0.6) selects top-5 diverse results — prevents returning 5 identical chunks about the same topic
4. Cross-encoder `ms-marco-MiniLM-L-6-v2` reranks the 5 chunks for precision
5. GPT-4o-mini generates the answer using only the retrieved context (grounded, no hallucination)
6. Source URLs returned alongside the answer

### AY versioning

Each assessment year gets its own FAISS namespace:
- `vector_store/AY2024-25.faiss` + `AY2024-25.meta.json`
- `vector_store/AY2025-26.faiss` + `AY2025-26.meta.json`

When new AY drops: ingest new PDFs → run embedder with `--ay AY2025-26` → only the RAG service redeploys. No other service is touched.

---

## 5. The agent pipeline

The LangGraph pipeline in `agent-orchestrator/graph/itr_graph.py` is a state machine. Every node receives the full `AgentState` dict and returns only what it changes. LangGraph merges the return into the state automatically.

```
Parsed documents (Form 16 JSON + bank statement JSON)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Node 1: fill_form                                            │
│                                                              │
│  For each document in raw_documents:                         │
│    if form16: extract salary, HRA, TDS, deductions          │
│    if bank_statement: extract interest income                │
│  Map every extracted value to itr1_schema.py path           │
│  Assign confidence (0–1) and source citation to each field   │
│  Compute derived values (net salary, 80TTA from interest)    │
│  Build TDSEntry objects for Schedule TDS1                    │
│  Compute gross total income                                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Node 2: compare_regimes                                      │
│                                                              │
│  Collect all old-regime deductions from filled form          │
│  Call compare_regimes() from tax_utils.py                    │
│  This runs actual slab math (NOT LLM inference):             │
│    Old regime: income − deductions → apply old slabs → 87A  │
│    New regime: income − ₹50,000 std ded → apply new slabs   │
│  Pick regime with lower total tax                            │
│  Fill tax_computation section of ITR-1 form                  │
│  Record: both taxes, saving, reasoning string                │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Node 3: validate                                             │
│                                                              │
│  12 validation checks:                                       │
│  [error]   Gross salary is 0 → Form 16 not parsed            │
│  [error]   Income > ₹50L → ITR-1 not applicable             │
│  [error]   HRA + 80GG both claimed → mutually exclusive      │
│  [error]   80TTA + 80TTB both claimed → only one allowed     │
│  [warning] Standard deduction is 0 when salary > 0          │
│  [warning] 80C family total > ₹1.5L                         │
│  [info]    Large refund (TDS > 1.5× tax) → verify from AIS  │
│  Each flag has: field, severity, message, suggestion         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Node 4: score_confidence                                     │
│                                                              │
│  Ensure all critical fields have a confidence score          │
│  Fields not found in documents → confidence 0.3, flagged     │
│  Compute average confidence across all fields                │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Node 5: explain                                              │
│                                                              │
│  GPT-4o-mini generates plain-English explanations for:       │
│  - Regime recommendation ("New regime saves ₹X because...")  │
│  - 87A rebate (if applicable)                                │
│  - HRA exemption calculation                                 │
│  Does NOT recompute numbers — uses numbers from state        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
                  Output: filled ITR1Form
                  + confidence_scores dict
                  + validation_flags list
                  + regime_analysis dict
                  + explanations dict
                  + audit_trail list
```

---

## 6. The document parsers

### Form 16 parser

Form 16 is issued by the employer and comes in two formats:
- **TRACES-generated** (standard): predictable label positions. The parser uses regex patterns that match the exact label text mandated by CBDT (e.g. "Salary as per provisions contained in section 17(1)").
- **Employer-generated**: variable layout. Falls back to pdfplumber's table extraction.

The parser extracts from Part A: employer TAN/PAN, employee PAN, TDS by quarter.
From Part B: gross salary (17(1)+17(2)+17(3)), every Sec 10 exemption (HRA, LTA), Sec 16 deductions (standard deduction, professional tax), all VI-A deductions as declared by employer (80C, 80D, etc.), taxable income, total TDS.

Returns `parse_confidence` which is the fraction of critical fields successfully extracted. If confidence < 0.5 it warns that the PDF may be scanned and needs OCR.

### Bank statement parser

Detects bank by regex against the header text (SBI, HDFC, ICICI, Axis). Each bank has slightly different column ordering and date formats — the parser handles all of them via `col()` function that searches column headers by keyword.

Classifies each transaction row by regex matching against the description:
- Salary: "NEFT", "PAYROLL", "SAL", monthly credit from employer
- Savings interest: "INT CREDITED", "SB INT", "QUARTERLY INT"
- FD interest: "FD INT", "TERM DEPOSIT INT", "TDR INT"
- TDS: "TDS DEDUCTED", "TAX DEDUCTED AT SOURCE"

Total savings interest → goes to `other_sources.savings_bank_interest` → 80TTA capped at ₹10,000.
Total FD interest → goes to `other_sources.fd_interest` → fully taxable under Other Sources.
Bank TDS → goes to Schedule TDS2 (TDS on income other than salary).

### AIS / Form 26AS parser

Reads the TDS credit table (deductor-wise). Separates Sec 192 (salary TDS → Schedule TDS1) from Sec 194A (interest TDS → Schedule TDS2) and other sections.

The key function is `reconcile_form16_vs_ais()` which compares:
- TDS shown in Form 16 Part A
- TDS shown in AIS under Sec 192

If these differ by more than ₹100, the validator raises an error. This catches the common case where an employer deducts TDS but doesn't deposit it, which causes an income tax notice after filing.

---

## 7. Setup — exact steps

### Prerequisites

- Docker Desktop (for docker compose)
- Python 3.11+ (for running knowledge-base scripts locally)
- OpenAI API key (for LLM answers and optionally embeddings)
- Node.js 20+ (only needed if running frontend outside Docker)

### Step 1: Put your files in the right places

```bash
# Your downloaded PDFs
cp ~/Downloads/*.pdf knowledge-base/pdfs/

# Your ITR-1 JSON schema (from ITD utility download)
cp ~/Downloads/ITR1*.json knowledge-base/form_files/

# Your ITR-1 Excel field map (if downloaded)
cp ~/Downloads/ITR1*.xlsx knowledge-base/form_files/
```

### Step 2: Configure environment

```bash
cp .env.example .env
# Edit .env and set:
# OPENAI_API_KEY=sk-...
# SKIP_AUTH=true     (keep this for local development)
```

### Step 3: Build the knowledge base

```bash
cd knowledge-base
pip install -r requirements.txt

# Install Playwright browser (one-time)
playwright install chromium

# Scrape the 5 official websites
python scraper.py

# Ingest your downloaded PDFs
python pdf_ingester.py

# Load the ITR-1 form schema
python itr_form_schema_loader.py

# Embed everything into FAISS (free — uses local model, no API cost)
python embedder.py --backend huggingface
```

After this you will have:
```
vector_store/
  AY2024-25.faiss
  AY2024-25.meta.json
```

### Step 4: Start all services

```bash
# Back to project root
cd ..
docker compose up --build
```

This starts: PostgreSQL → Redis → doc-parser → rag-service → agent-orchestrator → api-gateway → frontend.
Each service waits for its dependencies to pass health checks before starting.

First run takes ~5 minutes to build all Docker images.

### Step 5: Use the app

```
http://localhost:3000         → redirects to /upload
http://localhost:3000/upload  → document upload
http://localhost:3000/form    → filled form viewer (after pipeline runs)
http://localhost:3000/chat    → tax Q&A chat
```

### Step 6: Run tests

```bash
# From project root (no Docker needed — pure Python)
pip install pydantic pytest
pytest tests/test_tax_logic.py -v   # 38 tax logic tests
pytest tests/ -v                    # all tests (pipeline tests need langgraph installed)
```

### Checking service health

```bash
curl http://localhost:3001/api/health   # all services
curl http://localhost:8001/health       # RAG service + which AY loaded
curl http://localhost:8001/indexes      # which FAISS indexes are available
```

### If the scraper gets blocked

Some pages may return 403. Use the fallback:
```bash
python manual_fallback.py --all
# Or for a specific page that was blocked:
python manual_fallback.py --from-file saved_page.html --id itr1_faq
```
Last resort: open the page in Chrome, Ctrl+S to save as HTML, then run the `--from-file` option above.

---

## 8. What you need to provide

| Item | Where to get it | Where to put it |
|------|----------------|-----------------|
| OpenAI API key | platform.openai.com | `.env` file |
| ITR-1 instructions PDF (AY 2024-25) | incometaxindia.gov.in downloads page | `knowledge-base/pdfs/` |
| CBDT Circular 03/2025 | incometaxindia.gov.in/communications | `knowledge-base/pdfs/` |
| Income Tax Act relevant sections | indiacode.nic.in or indiankanoon.org | `knowledge-base/pdfs/` |
| ITR-1 JSON schema | ITD offline utility → extract from ZIP | `knowledge-base/form_files/` |
| ITR-1 Excel field map | Same ITD utility package | `knowledge-base/form_files/` |

The websites (incometax.gov.in pages, ClearTax) are scraped automatically by `scraper.py` — you don't download those.

---

## 9. Limitations

**What it does:**
- Parses Form 16, bank statements, AIS automatically
- Fills every ITR-1 field with source citations
- Compares old vs new regime with exact statutory math
- Validates for common errors and eligibility issues
- Answers tax questions in natural language with CBDT citations
- Exports a complete filled ITR-1 JSON

**What it does not do:**
- It does not submit the return to the income tax portal. The ITD portal does not provide a public API for programmatic filing. You export the JSON and import it into the ITD offline utility, or use it to fill the online portal manually (5 minutes vs 2 hours of manual work).
- It does not handle capital gains (Schedule CG) — those require ITR-2.
- It does not handle business income — that requires ITR-3.
- It does not handle more than one house property — ITR-2 required.
- It does not handle foreign income or assets.
- It does not give legal advice. All outputs should be reviewed before filing.

**ITR-1 eligibility (enforced by validator):**
- Salaried income only (one employer)
- Income from one house property
- Income from other sources (interest, dividends)
- Total income must not exceed ₹50 lakh
- Not a director in a company
- No agricultural income above ₹5,000

---

## 10. Interview cheat sheet

| Question | Answer |
|----------|--------|
| Why microservices? | Different scaling profiles — parser runs once per upload, RAG runs per query, agent runs per pipeline trigger. Language heterogeneity is justified: Python for ML ecosystem, Node for async I/O orchestration |
| Why Python for RAG/AI? | LangGraph, pdfplumber, FAISS, sentence-transformers — no equivalent in Node. Would lose 80% of ML tooling |
| Why Node.js for gateway? | Event-driven non-blocking I/O is the correct tool for orchestrating async calls to multiple Python microservices. Justifiable, not arbitrary |
| Why FAISS not Pinecone? | FAISS locally (zero cost, full control, fast for demo). Pinecone for production scale (managed, auto-scaling). Shows you know the tradeoff |
| How do you prevent hallucination? | RAG grounds answers in retrieved context. Confidence scoring flags fields not found in documents. Validator catches tax rule violations. Explain node uses context from state, not free generation |
| How is it AY-updatable? | Versioned FAISS namespaces (AY2024-25, AY2025-26). New AY: ingest new PDFs + re-run embedder → only RAG service redeploys. tax_utils.py AY_CONFIG dict has one entry per year |
| What does LangGraph add over raw prompting? | Models the pipeline as a state machine — each node has a defined contract (input state, output state). Resumable, testable in isolation, clear separation of concerns. Visualisable as a graph for viva |
| Why MMR retrieval? | Prevents 5 near-identical chunks being returned for a query. Balances relevance (similarity to query) with diversity (dissimilarity to already-selected chunks). Lambda=0.6 weights relevance higher |
| What is the cross-encoder for? | Re-ranks the 5 MMR results with a more expensive but accurate model. Bi-encoder (used for FAISS) is fast but approximate. Cross-encoder sees query+document together, much better precision |
| How does the tax computation work? | Deterministic Python math in tax_utils.py. NOT LLM inference. Exact statutory slab rates, 4% cess, marginal relief for surcharge, 3-component HRA minimum. Tested with 38 unit tests |
| What if Form 16 is scanned/image-based? | Parser returns parse_confidence < 0.5 and warns user. Fix: run `ocrmypdf scanned.pdf output.pdf` before uploading, which adds a text layer |
| How is the validator different from the form filler? | Validator is a separate LangGraph node that runs after filling, checks cross-field rules (HRA + 80GG, 80TTA + 80TTB, income cap), and produces structured ValidationFlag objects with severities |
