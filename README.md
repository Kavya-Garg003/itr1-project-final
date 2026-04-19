# ITR-1 RAG Agent — Full Project

AI-powered ITR-1 (Sahaj) filing assistant. Uploads Form 16 + bank statements → auto-fills all fields → compares tax regimes → validates → explains every decision.

---

## Architecture

```
Frontend (Next.js :3000)
    │
    ▼
API Gateway (Node.js/Express :3001)
    ├── Doc Parser (Python/FastAPI :8002)   ← Form 16, bank statements
    ├── RAG Service (Python/FastAPI :8001)  ← FAISS + LangChain QA
    └── Agent Orchestrator (Python/FastAPI :8000)  ← LangGraph pipeline
            └── LangGraph: fill → regime → validate → score → explain
```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- OpenAI API key (for LLM + embeddings)

### 1. Clone and configure
```bash
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY
```

### 2. Build the RAG knowledge base first
```bash
# Run knowledge-base/ scripts (see knowledge-base/README.md)
cd knowledge-base
pip install -r requirements.txt
python scraper.py          # scrapes ITR-1 official sources
python embedder.py --backend huggingface   # free, no extra cost
```

### 3. Start all services
```bash
docker compose up --build
```

### 4. Open the app
```
http://localhost:3000/upload
```

---

## Service map

| Service | Port | Tech | Role |
|---------|------|------|------|
| Frontend | 3000 | Next.js + Tailwind | Upload UI, form viewer, chat |
| API Gateway | 3001 | Node.js/Express | Auth, routing, file proxying |
| Agent Orchestrator | 8000 | Python/FastAPI + LangGraph | 5-step agent pipeline |
| RAG Service | 8001 | Python/FastAPI + LangChain | FAISS retrieval + LLM QA |
| Doc Parser | 8002 | Python/FastAPI + pdfplumber | Form 16 + bank statement parsing |
| PostgreSQL | 5432 | Postgres 16 | User data |
| Redis | 6379 | Redis 7 | Session cache |

---

## Agent pipeline (LangGraph)

```
parse_docs
    ↓
fill_form           ← maps Form 16 + bank data → ITR-1 fields
    ↓
compare_regimes     ← computes old vs new tax → recommends regime
    ↓
validate            ← checks limits, eligibility, cross-field rules
    ↓
score_confidence    ← assigns 0–1 confidence to each filled field
    ↓
explain             ← plain-English explanation for every field
    ↓
output              ← filled ITR-1 JSON + audit trail
```

---

## Knowledge base scraper
See `knowledge-base/README.md`. Sources scraped:
- incometax.gov.in ITR-1 user manual
- incometax.gov.in ITR-1 FAQs
- incometax.gov.in salaried guide
- ClearTax 80C guide
- ClearTax ITR-1 guide

---

## AY update procedure
When a new Assessment Year (e.g. AY 2025-26) drops:

```bash
# 1. Scrape new year's content
python knowledge-base/scraper.py --ay AY2025-26   # add new targets

# 2. Embed into separate namespace
python knowledge-base/embedder.py --ay AY2025-26

# 3. Update shared/tax_utils.py with new slab rates (only thing that changes)

# 4. Rebuild only rag-service
docker compose up --build rag-service
```
No other service is touched. This is the microservices story for interviews.

---

## Interview cheat sheet

| Question | Answer |
|----------|--------|
| Why microservices? | Different scaling — parser runs once per upload, RAG runs per query |
| Why Python for ML? | LangGraph, pdfplumber, FAISS — no equivalent in Node |
| Why Node for gateway? | Event-driven I/O, naturally suits async multi-service orchestration |
| Why FAISS not Pinecone? | FAISS locally, Pinecone for production scale — shows you know the tradeoff |
| How do you handle hallucination? | Confidence scoring + source citations + validator flags low-conf fields |
| How is it AY-updatable? | Versioned FAISS namespaces + per-AY config YAML, only RAG service redeploys |
| What does LangGraph add? | Models agent steps as a state machine — clean, testable, resumable |

---

## File structure

```
itr1-rag-agent/
├── shared/
│   ├── itr1_schema.py       ← Pydantic models for every ITR-1 field
│   └── tax_utils.py         ← Slab rates, 87A, HRA, regime comparison
├── doc-parser/
│   ├── main.py              ← FastAPI service
│   └── parsers/
│       ├── form16.py        ← Form 16 Part A + B extractor
│       └── bank_statement.py ← SBI/HDFC/ICICI interest extractor
├── rag-service/
│   └── main.py              ← FastAPI + LangChain FAISS QA
├── agent-orchestrator/
│   ├── main.py              ← FastAPI service
│   └── graph/
│       └── itr_graph.py     ← LangGraph 5-node pipeline
├── api-gateway/
│   └── src/index.js         ← Express + multer + JWT
├── frontend/
│   └── src/app/
│       ├── upload/page.tsx  ← Document upload UI
│       └── form/page.tsx    ← Filled form viewer + confidence bars
├── knowledge-base/          ← Scraper + embedder (see above)
└── docker-compose.yml
```
