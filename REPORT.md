# Report: Invoice Extraction Pipeline

All numbers below were produced by the commands in [Reproducing the numbers](#reproducing-the-numbers) on 2026-11-22. The generated report with per-document detail is [reports/accuracy_table.md](reports/accuracy_table.md); raw results are in `reports/eval_results.json`, `reports/eval_run_metadata.json` and `reports/batch_run_metadata.json`.

**Summary**

| | Result |
|---|---|
| Labelled set (10 docs), field accuracy | **80/80 (100%)** on the final run; **79/80 (98.8%)** on two earlier runs (see [Variance](#run-to-run-variance)) |
| Unlabelled set (10 docs) | All 10 schema-valid; 9 pass every check; **U04 flagged** for a genuine inconsistency in the document. A manual read found no extraction errors (an eyeball check, not ground truth). |
| Cost | **$0.0019 per document** at Groq list price (avg 1,997 tokens in / 1,005 out), about $0.04 for all 20 documents |
| Rule-based baseline (no LLM) | 92.5–93.8% on the labelled set, but only about 3 of 10 unlabelled docs fully correct: overfit (see [What did not work](#one-thing-that-did-not-work)) |

> **Honesty note:** the labelled set is small and I looked at it, and at three unlabelled documents, while building. Read 100% as "no errors on 10 documents I partly tuned against", not as an estimate of production accuracy. Details in [Overfitting disclosure](#overfitting-disclosure).

---

## 1. Approach

### Pipeline

```
file ─► load (PyMuPDF / Pillow) ─► bad-input checks ───────────────► error JSON (never sent to a model)
          │
          ├─ digital PDF (has a text layer) ─► layout text "cell | cell" ─► text LLM  (openai/gpt-oss-120b)
          └─ scan / photo ─► render 200 dpi ─► auto-upright ─► page images ─► vision LLM (qwen/qwen3.8-27b)
                                                                                │  JSON mode, temperature 0
                                                       normalise (numbers, dates, currency)
                                                                                │
                                         validate: Pydantic schema + arithmetic + consistency checks
                                                                                │ errors?
                                               corrective retry with the exact errors (max 2) ─► keep best attempt
                                                                                │
                                              outputs/<id>.json  +  needs_review / review_reasons / tokens / cost
```

### Model choice and why

Both models run on **Groq** (free tier for development, published per-token list prices for the cost estimate, fast inference). The pipeline routes each document to the input that loses the least information:

- **Digital PDFs → `openai/gpt-oss-120b` (text).** The PDF text layer gives every character and digit exactly, so an image would only add tokens and the risk of misreading. I rebuild the text into visual rows (`1 | Compute instances | 1440 | 0.09 | 122.40`) so table rows stay intact. gpt-oss is the cheapest strong reasoning model on Groq ($0.15 / $0.60 per 1M tokens), and reasoning helps with table and tax arithmetic.
- **Scans and photos → `qwen/qwen3.8-27b` (vision).** The model reads the page image directly. I tried OCR plus a text model first: RapidOCR took 4 to 9 s per page and scrambled column order on L10 and U05. Every OCR error then reached the LLM as a "fact".

Other backends (`openai`, `gemini`, `local` via Ollama, and the rule-based `no_ai` baseline) share the same interface and validation. A cloud backend without a key raises an error instead of silently falling back to the regex engine.

### Prompting

One system prompt ([config/prompts.py](config/prompts.py), version `v5`):

1. **Classify first.** Invoice vs purchase order, statement, letter, quotation, credit note and so on. If the document is not an invoice, every other field must be null (the validator enforces this too).
2. **Extraction rules restate the sample pack's labelling conventions** almost word for word: seller at the top, issue date (not due/PO date), `quantity` null when a row has none, discounts as negative rows, `tax_total` = sum of every tax line (0 if none), locale-aware numbers (`1.136,25`) and day/month order resolved from context.
3. **Helper fields that are not in the output.** The model also returns `unit_price` per row and `due_date`. They are dropped by the schema, but the validator uses them: `quantity × unit_price = amount` catches a code column read as quantity, and `invoice_date ≤ due_date ≤ invoice_date + 120 days` catches a misread year.
4. **Self-check instructions** (row arithmetic, sum + tax = total), JSON mode, temperature 0, fixed seed.
5. **Corrective retries.** When validation fails, the model gets its previous answer plus the validator's exact messages in the same conversation (up to 2 retries). The best-scoring attempt is kept. If errors survive, the document is returned with `needs_review: true` and the reasons. Bad data is never passed on silently.

### One thing that did not work

**A hand-tuned rule engine (regex plus layout heuristics, `--mode no_ai`).** It scores **93.8% (75/80)** on the labelled set with 150-dpi renders (**92.5%**, 74/80, under the final 200-dpi pipeline, because OCR reads L10 differently), and it looks good there because I wrote it while looking at those 10 files. On the 10 unlabelled documents, comparing its output with the documents by eye, only **about 3 of 10 were fully correct** (U03, U06, U10). Examples:

- vendor read as `"Amount(E)"` on U05;
- total `1.13` instead of `1136.25` on U08 (European number format);
- `null` date, items and total on the German invoice U07;
- tax under-counted on 5 of 8 invoices.

A 93.8% that falls apart off-sample is the clearest example of overfitting in this project. It is kept only as a labelled, offline baseline.

Two smaller things also failed and were fixed (both on U05, a page scanned at 90°):

- **Sending the sideways page as-is.** The vision model read invoice number `LP-10` instead of `LP-10932`. Fix: detect sideways text with RapidOCR's detector and rotate the page to the orientation that reads with higher confidence. This adds about 0.5 s per scan, about 7 s when a rotation is needed.
- **Rendering scans at 150 dpi.** After the rotation fix, the model consistently read "21 Oct 2026" as 2025, and it read the due date as 2025 too, so even the due-date check could not catch it. At 200 dpi it reads 2026. Cost: about 50 extra input tokens.

---

## 2. Accuracy

`python scripts/eval.py` on L01 to L10, Groq backend, prompt v5, 200 dpi:

| Field | Correct | Accuracy | Rule-based baseline (`--mode no_ai`) |
|---|---|---|---|
| `is_invoice` | 10/10 | 100% | 100% |
| `vendor` | 10/10 | 100% | 100% |
| `invoice_number` | 10/10 | 100% | 100% |
| `invoice_date` | 10/10 | 100% | 100% |
| `currency` | 10/10 | 100% | 100% |
| `line_items` | 10/10 | 100% | 60% |
| `tax_total` | 10/10 | 100% | 90% |
| `total` | 10/10 | 100% | 90% |
| **Overall** | **80/80** | **100%** | **92.5%** (74/80) |

- Documents with every field correct: 10/10. Line-item rows: precision 100%, recall 100% (66 rows).
- The labelled set covers 7 digital PDFs (one of them, L08, is a purchase order, i.e. a non-invoice) and 3 scans/photos (L02 photo, L09 and L10 scanned PDFs).

### Run-to-run variance

| Run | Config | Overall | Errors |
|---|---|---|---|
| A | prompt v4, 150 dpi | 79/80 (98.8%) | L03 `line_items`: one row's quantity wrong |
| B | prompt v5, 150 dpi | 79/80 (98.8%) | L03 `line_items`: one row's quantity wrong |
| C (final) | prompt v5, 200 dpi | 80/80 (100%) | none |

L03 is a digital PDF, so the DPI change cannot explain why it passed in run C. The model is simply not perfectly deterministic, even at temperature 0 with a seed. **The honest headline is 98.8–100% on the labelled set**, with line-item quantities as the weakest field.

### Matching rules (as implemented in [eval/metrics.py](eval/metrics.py))

| Field | Rule |
|---|---|
| `is_invoice` | exact boolean |
| `vendor` | lower-cased, punctuation removed, legal suffixes canonicalised (`Pvt Ltd` = `Private Limited`, `Ltd` = `Limited`, `Co` = `Company`, `B.V.` = `BV`, ...); match if equal or `fuzz.ratio ≥ 90`. **No subset matching**: `"Acme"` does **not** match `"Acme Pvt Ltd"`, because they could be different companies. |
| `invoice_number` | exact after trimming whitespace and upper-casing (`inv-1` = `INV-1`; `INV1` ≠ `INV-1`) |
| `invoice_date` | exact `YYYY-MM-DD` string |
| `currency` | exact ISO 4217 code, case-insensitive |
| `tax_total`, `total` | numeric, `|pred − gt| ≤ 0.01`. Strings are parsed first: `"1,200.00"` = `1200`, `"1.136,25"` = `1136.25`. |
| `line_items` | **strict**: same number of rows, in order, and every row matches: description similarity ≥ 80 (max of `ratio` / `token_sort_ratio` after normalisation), quantity equal or both null, amount within 0.01. Row-level precision/recall is reported as well, so one bad row is visible without hiding the strict score. |
| both null | counts as a match (non-invoices) |

---

## 3. Failure analysis

The final labelled run has no errors, so this section groups every error I observed: earlier labelled runs, the baseline, and the unlabelled documents I checked by hand. Causes are tagged automatically by `eval/metrics.py::classify_error` and printed in the eval report.

| # | Cause | Where seen | Example | Status |
|---|---|---|---|---|
| 1 | **Page geometry / resolution (scans)** | U05 (LLM) | 90° scan: `invoice_number` `LP-10` (truth `LP-10932`). At 150 dpi: `invoice_date` 2025-10-21 (truth 2026-10-21). | Fixed: auto-upright + 200 dpi. Not handled: 180° rotation, very low-resolution photos. |
| 2 | **Quantity column confusion** | L03 (LLM, 2 of 3 runs); L06, L07 (baseline) | LLM: one L03 row's quantity wrong. Baseline: amount copied into `quantity` on rows that have no quantity (should be `null`). | Mitigated by the `unit_price` helper + row check (`quantity × unit_price = amount`), which triggers a retry. Still flaky (variance above). |
| 3 | **Tax lines not summed** | L10 (baseline), 5 of 8 unlabelled invoices (baseline) | `tax_total` 9844.80 vs 19689.60: only CGST counted, SGST missed (`tax_half_counted`, 150-dpi run); at 200 dpi the same OCR text was over-counted instead | The LLM follows the "sum of every tax line" rule: 0 tax errors across 20 docs. |
| 4 | **OCR reading order** | L10, U05 (baseline) | Columns interleaved, so the vendor became `"Amount(E)"` and the header row became a line item | Avoided by sending scans to a vision model instead of OCR text. |
| 5 | **Locale** | U07 German, U08 Dutch (baseline) | `1.136,25` parsed as 1.13; `Rechnungsdatum` not recognised | The LLM plus `normalizer.parse_number` handle both. |
| 6 | **The document itself is inconsistent** | U04 (LLM) | Row 1 prints `1440 × 0.09 = 122.40` (should be 129.60) | Correct behaviour: report the printed values and flag. The pipeline does exactly that (`needs_review: true` with the reason). |

### What I would fix first

1. **Line-item quantity reliability (cause 2).** It is the only field that failed with the LLM. Plan: when the row check fails after retries, run a second sample (a different seed, or the vision model on the page image) and keep the rows on which both agree. Flag rows where they disagree.
2. **A bigger evaluation set.** 10 labelled docs cannot tell 95% from 100%. Hand-labelling the 10 unlabelled docs (I already read them) would double it; for real use, 50+ docs per layout family.
3. **A review flag that catches "consistent but wrong" errors.** See section 5: the flag misses errors that keep totals balanced (like the 2025 year). Plan: add cheap cross-checks such as the invoice number repeated in the footer, vendor vs the letterhead text layer, and agreement between two reads of the page.
4. **Orientation:** handle 180° pages; deskew phone photos.

---

## 4. Cost per document

**Method.** Each API response returns `prompt_tokens` and `completion_tokens`. For each call: `cost = prompt_tokens × input_price + completion_tokens × output_price`, summed per document (including corrective retries). Prices are loaded live from Groq's `/models` endpoint at run time ([ai_backends/groq_backend.py](ai_backends/groq_backend.py)), with a static fallback table in [pipeline/cost_tracker.py](pipeline/cost_tracker.py). The free tier billed $0; the figures are what a paid account would pay.

| Model | Input / 1M tokens | Output / 1M tokens |
|---|---|---|
| `openai/gpt-oss-120b` (digital PDFs) | $0.15 | $0.60 |
| `qwen/qwen3.8-27b` (scans/photos) | $0.80 | $4.00 |

| Set | Docs | Tokens in | Tokens out | Total | **Per document** |
|---|---|---|---|---|---|
| Labelled (eval) | 10 | 19,975 | 10,051 | $0.0190 | **$0.0019** |
| Unlabelled (batch) | 10 | 24,634 | 9,285 | $0.0192 | **$0.0019** |

| Route | Typical cost per doc | Why |
|---|---|---|
| Digital PDF → text model | $0.0003 – $0.0018 (avg ≈ $0.0010) | about 1,500 input tokens; output includes gpt-oss reasoning tokens (billed even though they are not returned) |
| Scan/photo → vision model | ≈ $0.0040 (U02: $0.0083, 2 calls) | about 2,900 input tokens per page image, at roughly 5× the price |

- Corrective retries are the main cost driver after the route: U04 needed 3 calls and U02 needed 2.
- **Projection:** 1,000 invoices a month with about 25% scans comes to roughly $1.75 a month at list price.
- **Latency.** A single call takes 2 to 8 s. On the free tier, throughput is capped by the per-model tokens-per-minute limit, so a client-side token bucket paces the 4 parallel workers. Ten documents took about 150 s, most of it queueing. With a paid tier, a 10-document batch would take about 15 s.

---

## 5. Bonus: is `needs_review` checked against the data?

`needs_review` is true when validation errors or warnings survive the retries: schema, arithmetic, row arithmetic, required fields, date consistency, truncated pages. Every output records it, with reasons, in `reports/*_run_metadata.json`. The eval computes how well it predicts real errors:

| Run | Docs flagged | Docs with ≥1 error | Precision | Recall | Field errors inside flagged docs |
|---|---|---|---|---|---|
| Rule-based baseline, labelled (150 dpi) | 3 | 4 | **1.00** | **0.75** | **4 of 5 (80%)** |
| Rule-based baseline, labelled (200 dpi, final) | 2 | 4 | **1.00** | **0.50** | 2 of 6 (33%) |
| LLM run A/B, labelled | 0 | 1 (L03) | n/a | 0.00 | 0 of 1 |
| LLM run C, labelled | 0 | 0 | n/a | n/a | n/a |
| LLM, unlabelled (manual check) | 1 (U04) | 0 extraction errors found | flag is a true document inconsistency | | |

**Reading it honestly:** the flag is **precise**. Everything it flagged was really wrong, either an extraction error or a broken source document. On the baseline it captured 33–80% of the errors, depending on the run: it reliably catches totals that don't add up, but L06/L07-style errors (a quantity where the truth is `null`) keep the arithmetic intact and slip through. But it can only catch errors that break a check: the L03 quantity miss and the 150-dpi year misread kept every total consistent and were not flagged. So it is useful for routing documents to a human, but not yet a guarantee. Fix 3 above targets this gap.

---

## 6. Bad inputs

| Case | Handling | Evidence |
|---|---|---|
| **Non-invoices** (L08 purchase order, U06 bank statement, U10 cover letter) | Classified first. `is_invoice: false` and the other 7 fields forced to `null` by the normaliser and the schema validator. | All 3 correct; L08 is in the labelled eval. |
| **Chosen case: corrupt or unreadable files** (0-byte file, truncated or garbage PDF, broken image, password-protected PDF, unsupported type) | Detected at load time and never sent to a model. Output: `{"error": "...", "error_type": "corrupt_file" \| "unsupported", "needs_review": true}`. The CLI exits with code 1, and a batch continues with the other files. | `tests/test_extractor.py::test_bad_files_never_reach_the_model` |
| **API failures** (rate limit, timeout, 5xx, daily quota, bad key) | 429: wait for `retry-after` / `x-ratelimit-reset-tokens`, with client-side token-bucket pacing. Timeout or 5xx: backoff and retry. Daily quota exhausted: clear error. Never a silent switch to another backend. Final failure gives `error_type: "backend_error"`. | `test_api_failure_is_graceful` |
| **Model returns invalid JSON** | One repair round-trip. Second failure gives `error_type: "unparseable"`. | `test_invalid_json_*` |
| **Sideways scans** | Auto-rotated before extraction (U05). | section 1 |

---

## Overfitting disclosure

- **Prompt rules** come from the sample pack's labelling conventions, not from specific documents. But I iterated on the prompt and the validator while looking at labelled results:
  - the null-quantity, helper `unit_price` and "sum every tax line" rules were sharpened after seeing errors on L03, L06, L07 and L10;
  - the matching rules were fixed before the final runs.
- **I looked at three unlabelled documents by eye while debugging**, and the U05 fixes (auto-rotation, 200 dpi, due-date check) came directly from U05:
  - **U05** is therefore not a blind result any more;
  - **U02**: I checked the invoice number against the photo;
  - **U04**: I confirmed the arithmetic inconsistency is in the document.
- No document-specific strings are in the LLM path. The rule engine's heuristics (keyword cues, column-position rules, an HSN-code skip) were written while looking at the labelled files, which is why it overfits.
- With 10 labelled documents, a single error moves accuracy by 1.25 points, and the observed run-to-run variance is about that size.

---

## Reproducing the numbers

```bash
python scripts/eval.py --mode groq                 # labelled eval: table, error groups, review check, cost
python scripts/eval.py --mode no_ai --no-save      # rule-based baseline, leaves outputs/ and reports/ alone
python scripts/batch.py "Es Magico - AI Intern Assignment - Sample Pack/unlabelled" --mode groq   # outputs/U*.json
python -m pytest tests -q                          # 32 tests, no network
```

Results are cached by file hash + model + prompt version + image-pipeline version (`.cache/`), so re-runs are free. Pass `--no-cache` (batch) or omit `--cache` (eval, the default) to force fresh API calls.
