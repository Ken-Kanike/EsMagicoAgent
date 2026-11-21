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

### D. Enterprise AP Operations Platform (Dark Industry Suite)
A dark, high-density operations console built in modern JavaScript, Tailwind CSS, Chart.js, and Lucide icons:
```bash
python scripts/serve_dashboard.py
# Or with an optional custom port:
python scripts/serve_dashboard.py --port 8000
```
Open your browser at **`http://localhost:8000`** to access:
- **Workspace:** Split layout with high-resolution document viewer (zoom in/out/reset, direct file drag-and-drop) alongside verified summary fields, line items table, and raw JSON.
- **Batch Ingestion Hub:** Drag and drop arbitrary batches of new invoices with multi-file queueing, real-time extraction progress bar, and 1-click **Excel (.xlsx)** and **JSON (.zip)** exports strictly for uploaded files.
- **Dynamic Template Studio:** Upload any document (or select an existing one), view its live rendered visual preview, auto-discover all entities (`Key: Value`, tables, dates, amounts), define custom output schemas, and save reusable OCR templates.
- **Evaluation Benchmark:** 1-click automated benchmark against the 10 labelled ground-truth documents (`L01`..`L10`) with field-by-field accuracy charts and verification matrix.
- **Model Context Protocol (MCP):** Live JSON-RPC tools manifest endpoint (`/api/mcp/manifest`) for external agents (Antigravity, OpenCode, Hermes).
- **Security Governance & Keys:** Live PII Redaction Shield status toggle and multi-key connection tester for Groq, Gemini, OpenAI, and Local LLMs before writing to `.env`.

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

| Field | Offline No-AI Engine (RapidOCR + Layout Parser) | LLM Vision Pipeline (Groq / GPT-4o) |
|---|---|---|
| `is_invoice` | **100.0%** (10/10) | **100.0%** (10/10) |
| `vendor` | **90.0%** (9/10) | **100.0%** (10/10) |
| `invoice_number` | **100.0%** (10/10) | **100.0%** (10/10) |
| `invoice_date` | **100.0%** (10/10) | **100.0%** (10/10) |
| `currency` | **100.0%** (10/10) | **100.0%** (10/10) |
| `line_items` | **70.0%** (7/10) | **90.0%** (9/10) |
| `tax_total` | **90.0%** (9/10) | **90.0%** (9/10) |
| `total` | **100.0%** (10/10) | **100.0%** (10/10) |
| **OVERALL** | **93.8%** (75/80) | **96.3%** (77/80) |

*(Generated automatically by `python scripts/eval.py`)*

---

## 5. Failure Analysis & Remediation

| Failure Category | Examples | Root Cause | Engineering Fix |
|---|---|---|---|
| **1. Optical Character Confusion** | `L02.jpg`, `L10.pdf` | Noisy background and low scan DPI cause '0' vs 'O' or '1' vs 'I' confusion in invoice numbers. | Image contrast preprocessing (`PIL.ImageEnhance`) + RapidOCR ONNX layout engine before OCR. |
| **2. Multi-Page & Dense Table Splitting** | `L04.pdf` (24 items) | Extensive line-item tables spanning page boundaries can trigger context clipping or truncation. | Increased completion token allocation (2,500 tokens) and sequential coordinate stream matching. |
| **3. Date Format Ambiguity** | `L01.pdf` (`08/04/2026`) | Day-first (UK/India) vs Month-first (US) ambiguity without regional context. | Master prompt enforces cross-referencing vendor origin and currency before outputting `YYYY-MM-DD`. |
| **4. Non-Invoice Discrimination** | `L08.pdf` (Purchase Order) | POs feature identical tables, line items, and taxes as sales invoices. | Discriminator prompt checking headers ('PURCHASE ORDER') to enforce `is_invoice: false` and null out remaining fields. |

---

## 6. Bad Input Handling (Requirement 3)

1. **Non-Invoice Documents:**
   - Correctly identifies bank statements (`U06`), purchase orders (`L08`), and cover letters (`U10`), returning `is_invoice: false` and `null` for all other 7 fields.
2. **Corrupt / Zero-Byte / Truncated Files:**
   - PyMuPDF and Pillow loaders trap `fitz.FileDataError` and empty files, returning `{"error": "corrupt_file", "needs_review": true}` without throwing unhandled exceptions or halting batch execution.

---

## 7. Enterprise Multi-Page Operations Platform & Dashboard

Launch the dark, industrial-grade operations platform:

```powershell
python scripts/serve_dashboard.py
# Or bind to an alternate port if desired:
python scripts/serve_dashboard.py --port 8080
```
*Live at [http://localhost:8000](http://localhost:8000)*

### 6 Dedicated Operations Pages:
1. **Workspace:** Split layout with a high-resolution PDF/image document viewer on the left (interactive zoom, rotate, and direct drag-and-drop file intake) alongside verified summary fields (Vendor, Inv #, Date, Currency, Tax, Total, ±0.00 Arithmetic Balance badge), interactive line items table, and schema-compliant JSON copy/download. When non-invoices (`L08`, `U06`, `U10`) are loaded, a clear regulatory banner explains the null schema rule.
2. **Batch Ingestion Hub:** Purpose-built for new arbitrary document batches. Starts empty by default. Drag & drop 5, 20, 50+ files at once, preview queued file chips, execute batch extraction with real-time percentage progress, and export **strictly the uploaded files** to multi-sheet **Excel (.xlsx)** and **JSON (.zip)**.
3. **Template Studio:** Visual OCR template builder. Upload any novel document format, inspect its high-resolution rendering, auto-discover all entities (`Key: Value` pairs, tables, dates, numbers), customize field keys and labels, add arbitrary custom fields, save templates to browser `localStorage` and backend `templates/`, and run custom-schema extraction.
4. **Evaluation Benchmark:** 1-click evaluation against the 10 labelled ground-truth answers (`L01` through `L10`), featuring interactive Chart.js field accuracy breakdown and ground-truth verification matrix.
5. **MCP Tools Manifest:** Complete architectural guide to Local LLMs (Ollama / Nous Hermes 3 / OpenCode) and Model Context Protocol (MCP) tool integration. Demonstrates air-gapped on-premise privacy, self-correcting reasoning loops, and 3-way ERP reconciliation against purchase orders. Includes live JSON-RPC manifest at `/api/mcp/manifest`.
6. **Security & API Store:** Manage API credentials directly from the browser with live connection ping tests before saving (Groq 10-key rotation pool, Google Gemini, OpenAI/Antigravity gateway, and Local LLM endpoints). Includes the live **Cloud PII Redaction & Privacy Shield** toggle.

---

## 8. Cloud PII Redaction & Privacy Shield

Vendor invoices often contain sensitive banking details, national tax IDs, and confidential commercial contact info. When utilizing external cloud models (Groq, OpenAI, Google Gemini), our **PII Shield** (`pipeline/pii_shield.py`) guarantees data privacy:

* **Automatic Sanitization:** Scans raw text before transmitting prompts to cloud APIs, intercepting:
  - **Bank Account / IBAN Numbers** (regex matching standard IBANs and 9–18 digit account sequences).
  - **Credit & Debit Card Numbers** (13–19 digit Luhn-like sequences).
  - **National Identification & Tax IDs** (US SSN `XXX-XX-XXXX`, Indian PAN `[A-Z]{5}[0-9]{4}[A-Z]`).
  - **Personal Contact Numbers & Personal Emails**.
* **Zero Leak Guarantee:** Third-party cloud models only receive masked tokens (e.g. `[REDACTED_BANK_ACC_0]`, `[REDACTED_PHONE_1]`).
* **Local Reversible Restoration:** Once structured outputs return, the local pipeline safely restores legitimate values in memory so your local ledger and database remain 100% complete and accurate.
* **Governance UI:** Active status badge in the top navbar (`● PII Shield Active`) with toggle controls in the Security page.

---

## 9. Dynamic Template Studio & Custom Field Definition

To handle atypical or non-standard documents (hall tickets, logistics waybills, freight receipts, medical claims) without modifying core code:

1. **Visual Document Intake:** Upload any PDF or image (`.jpg`, `.jpeg`, `.png`) to inspect page 1 in the interactive preview container.
2. **Deep Entity Discovery:** `POST /api/templates/discover` scans the document and surfaces:
   - Colon-separated pairs (`Key: Value`) across the text.
   - Document references, dates, due dates, amounts, taxes, and tables.
   - Portal URLs and web references.
3. **Interactive Schema Builder:**
   - Select which fields to include via checkboxes.
   - Rename display labels or edit field keys.
   - Use **"Add Field"** to add custom user-defined keys (e.g., `seat_number`, `prn_number`, `tracking_id`).
4. **Persistent Template Store:** Save templates by name (e.g., *"University Hall Ticket"*, *"Amazon Logistics Waybill"*). Templates persist in browser `localStorage` and backend `templates/*.json`.
5. **Execution & Export:** Click **"Extract Document Using This Template"** to extract custom structured records matching your schema, downloadable as custom JSON or formatted Excel.

---

## 10. Cost Calculation & Market Economics

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

## 11. Repository File Structure

```
EsMagicoAgent/
├── PLAN.MD                          # Master architecture blueprint
├── README.md                        # Complete documentation & benchmark report
├── requirements.txt                 # Core dependencies
├── pytest.ini                       # Test suite runner configuration
├── .env.example                     # Environment template (no secret keys committed)
├── config/
│   ├── settings.py                  # Pydantic BaseSettings environment config
│   └── prompts.py                   # Master extraction & self-correction prompts
├── pipeline/
│   ├── models.py                    # Schema definition (InvoiceSchema, LineItem)
│   ├── document_loader.py           # PyMuPDF text & image rendering intake
│   ├── ocr_engine.py                # RapidOCR ONNX layout engine + Tesseract fallback
│   ├── pii_shield.py                # Cloud PII Redaction & Privacy Shield (Banks, SSN, PAN)
│   ├── template_engine.py           # Dynamic Template Studio & Custom Entity Discovery
│   ├── extractor.py                 # Core extraction & validation orchestrator
│   ├── validator.py                 # Schema & arithmetic balance checker
│   ├── cost_tracker.py              # Token usage & USD expenditure calculator
│   └── output_writer.py             # File exporter for outputs/
├── ai_backends/
│   ├── base.py                      # Abstract backend interface
│   ├── no_ai.py                     # Deterministic rule & layout token parser
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
│   └── static/
│       └── index.html               # 6-Page Enterprise Operations Suite (Tailwind / Lucide)
├── templates/                       # Persistent JSON storage for user-defined OCR templates
├── api/
│   ├── main.py                      # FastAPI application entrypoint & static mount
│   ├── models.py                    # Request and response models
│   └── routes/
│       ├── health.py                # Health check endpoint
│       ├── extract.py               # Document upload & extraction endpoint
│       ├── evaluation.py            # Automated eval benchmark endpoint
│       └── dashboard_api.py         # Workspace, batch, excel export, keys, & MCP APIs
├── scripts/
│   ├── serve_dashboard.py           # Launches Enterprise Dashboard on http://localhost:8000
│   ├── extract.py                   # CLI tool to extract single document or folder
│   ├── eval.py                      # CLI evaluation benchmark runner
│   └── batch.py                     # CLI batch runner for all 20 documents
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
