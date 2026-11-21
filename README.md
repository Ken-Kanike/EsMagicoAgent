# EsMagico | AI Intern Assignment — Invoice Extraction Pipeline

A production-grade, multi-backend intelligent invoice extraction and validation pipeline designed to parse messy vendor invoices (clean PDFs, smartphone camera scans, multi-page tables) into strictly validated JSON conforming to `schema.json`.

---

## 1. Quick Setup & Fresh Clone Instructions

### Prerequisites
- Python 3.10+ (tested on Python 3.12)
- *(Optional for image OCR)* Tesseract OCR binary:
  - Windows: `winget install UB-Mannheim.TesseractOCR`
  - Linux: `sudo apt-get install tesseract-ocr`

### Installation
```bash
# 1. Clone repository
git clone <repo-url>
cd EsMagicoAgent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env to add your Groq keys, local Ollama endpoint, or OpenAI keys
```

### Verify Installation
```bash
python scripts/install_deps.py
```

---

## 2. Running the Pipeline

### A. Single Document CLI (Piping Supported)
Extract structured JSON from any file directly to stdout:
```bash
python scripts/extract.py "Es Magico - AI Intern Assignment - Sample Pack/labelled/L01.pdf" --mode no_ai > out.json
```
Options:
- `--mode`: `no_ai` (rule engine), `groq` (cloud multi-key pool), `local` (Ollama/Hermes), `gemini`, `openai`, `antigravity`.
- `--save / --no-save`: Auto-saves output into `outputs/<doc_id>.json` (default: enabled).

### B. One-Command Evaluation Harness (25% Weight)
Evaluate against all 10 ground truth labelled documents (`L01` through `L10`):
```bash
python scripts/eval.py
```
Or specify a backend:
```bash
python scripts/eval.py --mode no_ai
python scripts/eval.py --mode groq
```
Generates a Rich terminal table, per-document matrix, cost calculations, and markdown reports in `reports/accuracy_table.md`.

### C. Batch Processing
Process an entire folder (e.g. unlabelled test pack):
```bash
python scripts/batch.py "Es Magico - AI Intern Assignment - Sample Pack/unlabelled" --mode no_ai
```

### D. Interactive Business Dashboard (Streamlit)
```bash
streamlit run dashboard/app.py
```
Includes side-by-side document preview vs. extracted JSON, batch runner with progress bar, live evaluation dashboard, and client ROI calculators.

### E. Production REST API (FastAPI)
```bash
uvicorn api.main:app --reload --port 8000
```
Interactive Swagger documentation available at: `http://localhost:8000/docs`
- `GET /health` — Service health & key pool status
- `POST /extract` — Upload invoice file, receive validated JSON
- `GET /eval` — Trigger evaluation benchmark

### F. Run Automated Unit Tests
```bash
pytest tests/ -v
```

---

## 3. Architecture & Approach

### Multi-Backend Strategy
The pipeline is decoupled through an abstract `AIBackend` interface:
1. **No-AI Deterministic Engine (`no_ai`):** High-speed regex and layout heuristics extracting text via PyMuPDF (`fitz`). Zero external API calls, \$0.00 cost.
2. **Groq Cloud Multi-Key Pool (`groq`):** Uses an intelligent round-robin rotator supporting up to 10 free API keys. Automatically intercepts HTTP 429 rate limits, triggers 65-second per-key cooldowns, and routes image scans to `meta-llama/llama-4-scout-17b-16e-instruct` and text to `llama-3.3-70b-versatile`.
3. **Local LLMs (`local`):** Connects to any local OpenAI-compatible inference engine (Ollama, LM Studio, llama.cpp, NousResearch Hermes 3, or OpenCode) for 100% data privacy.
4. **Google Gemini & OpenAI / Antigravity (`gemini`, `openai`, `antigravity`):** Native gateway integrations for commercial-grade accuracy.

### Schema & Arithmetic Validation Engine
Every document passes through Pydantic v2 validation adhering strictly to `schema.json`:
- **Conditional Non-Invoice Check:** If `is_invoice == false`, all other 7 fields (`vendor`, `invoice_number`, `invoice_date`, `currency`, `line_items`, `tax_total`, `total`) are verified to be `null`.
- **Arithmetic Balance Verification:** Checks that $\sum(\text{line\_items.amount}) + \text{tax\_total} = \text{total}$ within a configurable floating-point tolerance ($\pm 0.05$).
- **Autonomous Self-Correction:** When an arithmetic or schema discrepancy is flagged, the pipeline prompts the LLM with the exact validation error message for a targeted retry.

### What We Tried That Did Not Work (Honest Finding)
- **Pure Regex on Low-Resolution Scans (`L02.jpg`):** While our rule-based engine achieved 70% accuracy on digital PDF vendors and dates, it achieves 0% on pure image scans without OCR or vision models. Layout variations, non-standard tabular delimiters, and optical noise make pure heuristic parsers brittle. Integrating multi-modal vision (`llama-4-scout` / `gpt-4o`) was essential for scans.

---

## 4. Evaluation & Accuracy Results

Matching rules applied in `eval/metrics.py`:
- `is_invoice`: Exact boolean match.
- `vendor`: RapidFuzz `token_set_ratio >= 85%` (resilient to legal suffix abbreviations like "Pvt Ltd" vs "Private Limited").
- `invoice_number`: Exact uppercase normalized string.
- `invoice_date`: Strict ISO 8601 `YYYY-MM-DD`.
- `currency`: Exact 3-letter ISO 4217 code.
- `line_items`: Sequential row check (description fuzzy >= 70%, amount within ±0.05).
- `tax_total` & `total`: Absolute difference <= 0.05.

### Accuracy Table (Labelled Dataset L01 - L10)

| Field | No-AI Baseline | LLM Vision Pipeline (Groq / GPT-4o) |
|---|---|---|
| `is_invoice` | **70.0%** (7/10) | **100.0%** (10/10) |
| `vendor` | **70.0%** (7/10) | **100.0%** (10/10) |
| `invoice_number` | **10.0%** (1/10) | **90.0%** (9/10) |
| `invoice_date` | **60.0%** (6/10) | **100.0%** (10/10) |
| `currency` | **70.0%** (7/10) | **100.0%** (10/10) |
| `line_items` | **10.0%** (1/10) | **90.0%** (9/10) |
| `tax_total` | **10.0%** (1/10) | **90.0%** (9/10) |
| `total` | **10.0%** (1/10) | **100.0%** (10/10) |
| **OVERALL** | **38.8%** (31/80) | **96.3%** (77/80) |

*(Generated automatically by `python scripts/eval.py`)*

---

## 5. Failure Analysis & Remediation

| Failure Category | Examples | Root Cause | Engineering Fix |
|---|---|---|---|
| **1. Optical Character Confusion** | `L02.jpg`, `L10.pdf` | Noisy background and low scan DPI cause '0' vs 'O' or '1' vs 'I' confusion in invoice numbers. | Image contrast preprocessing (`PIL.ImageEnhance`) before OCR, or feeding raw image to vision model. |
| **2. Multi-Page & Dense Table Splitting** | `L04.pdf` (24 items) | Extensive line-item tables spanning page boundaries can trigger context clipping or truncation. | Increased completion token allocation (2,500 tokens) and dedicated row sequence matching. |
| **3. Date Format Ambiguity** | `L01.pdf` (`08/04/2026`) | Day-first (UK/India) vs Month-first (US) ambiguity without regional context. | Master prompt enforces cross-referencing vendor origin and currency before outputting `YYYY-MM-DD`. |
| **4. Non-Invoice Discrimination** | `L08.pdf` (Purchase Order) | POs feature identical tables, line items, and taxes as sales invoices. | Discriminator prompt checking headers ('PURCHASE ORDER') to enforce `is_invoice: false` and null out remaining fields. |

---

## 6. Bad Input Handling (Requirement 3)

1. **Non-Invoice Documents:**
   - Correctly identifies bank statements (`U06`), purchase orders (`L08`), and cover letters (`U10`), returning `is_invoice: false` and `null` for all other 7 fields.
2. **Corrupt / Zero-Byte / Truncated Files:**
   - PyMuPDF and Pillow loaders trap `fitz.FileDataError` and empty files, returning `{"error": "corrupt_file", "needs_review": true}` without throwing unhandled exceptions or halting batch execution.

---

## 7. Cost Calculation & Market Economics

### Actual Token & API Cost (10 Sample Documents)
- **Average Prompt Tokens per Document:** 2,160 tokens
- **Average Completion Tokens per Document:** 405 tokens
- **Groq Free Tier (10-key rotation):** **\$0.000000 USD**
- **Commercial GPT-4o-mini Rate:** **\$0.000567 USD per document**

### Market Cost Comparison
- **Manual Human Data Entry:** \$12.00 – \$18.00 per invoice (fully loaded labor).
- **Enterprise IDP (Rossum, ABBYY):** \$0.20 – \$0.60 per invoice (+ \$15k/yr platform retainer).
- **Hyperscale Cloud (AWS Textract, Google DocAI):** \$0.015 – \$0.025 per document.
- **This Pipeline (Groq Free / Local LLM):** **\$0.0000 per document**.
- **This Pipeline (GPT-4o-mini):** **~\$0.0006 per document**.

*For an SMB processing 500 invoices/month, switching from manual entry to this automated pipeline yields over **\$89,900 in net annual savings (>2,900,000% ROI)**.*

---

## 8. Repository File Structure

```
EsMagicoAgent/
├── PLAN.MD                          # Master architecture blueprint
├── README.md                        # Documentation & submission report
├── requirements.txt                 # Core dependencies
├── pytest.ini                       # Test suite runner configuration
├── .env.example                     # Environment template (no secret keys committed)
├── config/
│   ├── settings.py                  # Pydantic BaseSettings environment config
│   └── prompts.py                   # Master extraction & self-correction prompts
├── pipeline/
│   ├── models.py                    # Schema definition (InvoiceSchema, LineItem)
│   ├── document_loader.py           # PyMuPDF text & image rendering intake
│   ├── ocr_engine.py                # Tesseract OCR & image contrast enhancement
│   ├── extractor.py                 # Core extraction & validation orchestrator
│   ├── validator.py                 # Schema & arithmetic balance checker
│   ├── cost_tracker.py              # Token usage & USD expenditure calculator
│   └── output_writer.py             # File exporter for outputs/
├── ai_backends/
│   ├── base.py                      # Abstract backend interface
│   ├── no_ai.py                     # Deterministic rule & regex engine
│   ├── groq_backend.py              # 10-key rotation pool with 429 cooldowns
│   ├── local_llm.py                 # OpenAI-compatible local harness (Ollama/Hermes)
│   ├── gemini_backend.py            # Google Gemini 1.5 Flash client
│   ├── openai_backend.py            # OpenAI & Antigravity gateway client
│   └── router.py                    # Dynamic backend resolution
├── eval/
│   ├── metrics.py                   # Matching rules (fuzzy vendor, dates, tolerances)
│   ├── harness.py                   # One-command evaluation harness (L01 - L10)
│   └── report.py                    # Terminal Rich table & markdown reporter
├── dashboard/
│   └── app.py                       # Streamlit operational business UI
├── api/
│   ├── main.py                      # FastAPI application entrypoint
│   ├── models.py                    # Request and response models
│   └── routes/
│       ├── health.py                # Health check endpoint
│       ├── extract.py               # Document upload & extraction endpoint
│       └── evaluation.py            # Automated eval benchmark endpoint
├── agents/
│   ├── extraction_agent.py          # Autonomous agent with retry loop
│   ├── opencode_agent.json          # OpenCode harness configuration
│   └── skills/                      # Antigravity agent skill definitions
│       ├── extract_invoice.md
│       ├── run_eval.md
│       └── batch_process.md
├── outputs/                         # All 20 document JSON outputs (L01..L10, U01..U10)
├── reports/                         # Generated accuracy and cost reports
└── tests/                           # Pytest unit & integration test suite
```
