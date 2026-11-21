---
name: run-eval
description: Execute the full evaluation harness over the 10 labelled sample invoices, printing field accuracy tables and exporting reports.
---

# Run Evaluation Skill

Runs the single-command evaluation harness comparing extracted fields against ground truth answers in `labelled/`.

## Command
```bash
python scripts/eval.py [--mode no_ai|groq|local|gemini|openai]
```

## Evaluated Fields & Matching Rules
1. `is_invoice`: Exact boolean match (catches non-invoices like Purchase Orders and Statements).
2. `vendor`: RapidFuzz `token_set_ratio >= 85%` (resilient to punctuation & suffix differences like "Pvt Ltd" vs "Pvt. Ltd.").
3. `invoice_number`: Exact uppercase normalized string.
4. `invoice_date`: Strict ISO `YYYY-MM-DD` string match.
5. `currency`: Standard 3-letter ISO 4217 code.
6. `line_items`: Table row sequence match (desc fuzzy >= 80%, amount within ±0.05).
7. `tax_total`: Absolute difference <= 0.05.
8. `total`: Absolute difference <= 0.05.

## Generated Artifacts
- Terminal Rich table display.
- Markdown summary at `reports/accuracy_table.md`.
- Token and USD cost analysis at `reports/cost_report.md`.
