# Invoice Extraction Pipeline

**Live demo: [esmagicoagent.onrender.com](https://esmagicoagent.onrender.com/)** (Render free tier: the first load after idle takes about a minute)

![Dashboard overview](docs/dashboard.png)

Reads a vendor invoice (clean PDF, phone scan or photo) and returns validated JSON in the assignment schema. It handles non-invoices and corrupt files, and includes a one-command evaluation, outputs for all 20 sample documents, a dashboard and an MCP server.

**Results** (10 labelled documents, Groq `qwen/qwen3.8-27b` vision + `openai/gpt-oss-120b` text):
- **80/80 fields (100%)** on the final run, and 79/80 on two earlier runs;
- **$0.0019 per document** at list price.

The prompt was refined while looking at the labelled set. The approach, accuracy table, failure analysis, cost method and overfitting disclosure are in **[REPORT.md](REPORT.md)**.

---

## Setup

Requires Python 3.10+ (tested on 3.12). No system binaries are needed.

```bash
git clone <repo-url> && cd EsMagicoAgent
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
# add a Groq key to .env:   GROQ_API_KEY_1=gsk_...   (free at https://console.groq.com)
```

To check the setup without a key: `python -m pytest tests -q` and `python scripts/eval.py --mode no_ai --no-save`.

## Usage

| Task | Command |
|---|---|
| Extract one document | `python scripts/extract.py invoice.pdf > out.json` |
| …with review flag, reasons, tokens and cost | `python scripts/extract.py invoice.pdf --meta` |
| **Evaluate on the 10 labelled documents** | `python scripts/eval.py` |
| Batch a folder (writes `outputs/`) | `python scripts/batch.py "Es Magico - AI Intern Assignment - Sample Pack/unlabelled"` |
| Dashboard + REST API | `python scripts/serve_dashboard.py` → http://localhost:8000 (API docs at `/docs`) |
| MCP server (stdio) | `python scripts/mcp_server.py` |
| Tests | `python -m pytest tests -q` |

`--mode groq|openai|gemini|local|no_ai` selects the backend. A cloud backend without a key raises an error instead of silently falling back.

## Approach

```
file ─► load + bad-input checks ───────────────────────────────► typed error (never sent to a model)
          ├─ digital PDF (text layer) ─► text LLM   (gpt-oss-120b, JSON mode)
          └─ scan / photo ─► auto-upright, 200 dpi ─► vision LLM (qwen3.8-27b, JSON mode)
                                         │
               normalise ─► validate ─► corrective retry (max 2) ─► JSON + needs_review
```

The prompt restates the sample pack's labelling rules:
- vendor = the seller;
- issue date, not due date;
- `quantity = null` when a row has none;
- discounts are negative line items;
- `tax_total` = the sum of all tax lines.

Details and the reasons for this design are in [REPORT.md](REPORT.md).

## Validation and bad inputs

**Checks:**
- Pydantic schema; a non-invoice must have every other field `null`;
- required fields present;
- `|Σ line amounts + tax − total| ≤ max(0.05, 0.01 × rows)`;
- quantity × unit price = amount;
- issue date consistent with the due date.

**On failure:** the model retries with the exact errors (up to 2 times). Anything still failing is returned with `needs_review: true` and `review_reasons`, never passed on silently.

| Bad input | Handling |
|---|---|
| Not an invoice (PO, bank statement, letter) | `is_invoice: false`, every other field `null` |
| **Chosen case: corrupt or unreadable file** (empty, truncated, garbage, password-protected, unsupported type) | Caught at load time and never sent to a model. Returns `{"error", "error_type", "needs_review": true}`; the CLI exits 1 and a batch continues |
| API failure (rate limit, timeout, 5xx) | Backoff and retry, then `error_type: "backend_error"` |

## Evaluation matching rules

`python scripts/eval.py` prints a field-level accuracy table, a per-document matrix, errors grouped by cause, the `needs_review` check and the cost, and writes [reports/accuracy_table.md](reports/accuracy_table.md).

| Field | Rule |
|---|---|
| `is_invoice` | exact |
| `vendor` | case/punctuation-insensitive, legal suffixes normalised (Pvt Ltd = Private Limited), `fuzz.ratio ≥ 90`; no subset matching |
| `invoice_number` | exact after trimming whitespace and upper-casing |
| `invoice_date`, `currency` | exact (ISO date, ISO 4217 code) |
| `tax_total`, `total` | within 0.01 after parsing (`"1,200.00"` = `1200`) |
| `line_items` | same rows in order; description fuzz ≥ 80, quantity equal or both null, amount within 0.01 |
| both `null` | match |

## Deployment

Deployed on **[Render](https://esmagicoagent.onrender.com/)** as a Docker web service ([Dockerfile](Dockerfile), [render.yaml](render.yaml)).

## Project layout

```
pipeline/          loader, OCR, extractor (retry loop), normaliser, validator, templates, cost, tools
ai_backends/       Groq (key rotation, rate limiting), OpenAI/Gemini/local, rule-based baseline
eval/              matching rules, harness, report
api/               FastAPI app and routes
dashboard/static/  dashboard (HTML, CSS, JS)
scripts/           extract.py · eval.py · batch.py · serve_dashboard.py · mcp_server.py
outputs/           JSON for all 20 documents
reports/           generated accuracy table and run metadata
tests/             offline tests
REPORT.md          approach, accuracy, failure analysis, cost
```
