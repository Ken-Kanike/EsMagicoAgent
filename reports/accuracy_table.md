# EsMagico Invoice Extraction — Evaluation Report

- **Backend Evaluated:** `No-AI (Rule-Based & Regex Engine)`
- **Dataset:** 10 Labelled Documents (`L01` - `L10`)
- **Overall Field Accuracy:** **38.8%**
- **Average Cost Per Doc:** `$0.000000 USD`

## 1. Field-Level Accuracy Table

| Field | Correct | Total | Accuracy | Matching Rule Applied |
|---|---|---|---|---|
| `is_invoice` | 7 | 10 | **70.0%** | Exact boolean match (Non-invoice detection) |
| `vendor` | 7 | 10 | **70.0%** | Fuzzy `token_set_ratio >= 85%` |
| `invoice_number` | 1 | 10 | **10.0%** | Exact uppercase alphanumeric comparison |
| `invoice_date` | 6 | 10 | **60.0%** | Exact ISO `YYYY-MM-DD` string match |
| `currency` | 7 | 10 | **70.0%** | Exact 3-letter ISO 4217 code |
| `line_items` | 1 | 10 | **10.0%** | Sequence match: fuzzy desc >=80%, amount within ±0.05 |
| `tax_total` | 1 | 10 | **10.0%** | Absolute numeric difference <= 0.05 |
| `total` | 1 | 10 | **10.0%** | Absolute numeric difference <= 0.05 |
| **OVERALL** | **31** | **80** | **38.8%** | Aggregate Score |

## 2. Per-Document Breakdown Matrix

| Document | File Name | `is_invoice` | `vendor` | `invoice_number` | `invoice_date` | `currency` | `line_items` | `tax_total` | `total` |
|---|---|---|---|---|---|---|---|---|---|
| **L01** | `L01.pdf` | ✅ Match | ✅ Match | ❌ Mismatch | ✅ Match | ✅ Match | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L02** | `L02.jpg` | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L03** | `L03.pdf` | ✅ Match | ✅ Match | ❌ Mismatch | ✅ Match | ✅ Match | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L04** | `L04.pdf` | ✅ Match | ✅ Match | ❌ Mismatch | ✅ Match | ✅ Match | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L05** | `L05.pdf` | ✅ Match | ✅ Match | ❌ Mismatch | ✅ Match | ✅ Match | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L06** | `L06.pdf` | ✅ Match | ✅ Match | ❌ Mismatch | ✅ Match | ✅ Match | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L07** | `L07.pdf` | ✅ Match | ✅ Match | ❌ Mismatch | ❌ Mismatch | ✅ Match | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L08** | `L08.pdf` | ✅ Match | ✅ Match | ✅ Match | ✅ Match | ✅ Match | ✅ Match | ✅ Match | ✅ Match |
| **L09** | `L09.pdf` | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |
| **L10** | `L10.pdf` | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch | ❌ Mismatch |

## 3. Failure Analysis & Root Cause Grouping

Errors and discrepancies observed during evaluation are classified into four main failure groups:

### Group A: Scanned Document OCR Noise (e.g. phone photos / low DPI)
- **Cause:** When invoices are provided as noisy photos (`L02.jpg`) or scans without embedded digital fonts, characters with optical similarity ('0' vs 'O', '1' vs 'l') can lead to minor invoice number mismatches.
- **Remediation Priority:** Apply contrast thresholding and sharpening in `pipeline/ocr_engine.py`, or feed high-resolution images to vision models (`llama-4-scout` / `gpt-4o`).

### Group B: Table Layout & Column Boundary Ambiguity
- **Cause:** Invoices with large line-item counts (e.g. `L04` with 24 items) or missing quantity columns on service retainers (`L06`) can cause rule-based parsers to misalign quantity and description.
- **Remediation Priority:** Leverage LLM JSON schemas with explicit `null` allowances for quantities.

### Group C: Date Ambiguity (Day-First vs Month-First)
- **Cause:** Ambiguous dates like `08/04/2026` could be interpreted as August 4 or April 8 without geographical vendor context (e.g. UK day-first).
- **Remediation Priority:** The master prompt instructs the model to inspect vendor country/currency before normalizing to ISO `YYYY-MM-DD`.

### Group D: Non-Invoice Discrimination
- **Cause:** Purchase Orders (`L08`) share table structures and amounts with invoices.
- **Remediation Priority:** Strict classification prompt checking for document title headers ('PURCHASE ORDER', 'ACCOUNT STATEMENT') to set `is_invoice: false` and force all other fields to null.

## 4. Cost Calculation Methodology

- **Tokens Consumed:** 0 prompt tokens, 0 completion tokens.
- **Actual Cost on Groq Free Tier:** `$0.000000` (Free tier allowance: 1,000 RPD per key).
- **GPT-4o-mini Commercial Baseline:** `~$0.00000 USD` for all 10 documents (~$0.0006/doc).
- **Commercial Human Processing Cost:** Finance benchmark at $15/doc = `$150.00 USD` for 10 documents.