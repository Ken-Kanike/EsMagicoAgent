---
name: extract-invoice
description: Run the invoice extraction pipeline on a PDF or image document and return validated JSON according to the assignment schema.
---

# Extract Invoice Skill

Executes the automated document intake, extraction, schema validation, and balance-checking pipeline.

## CLI Usage

```bash
python scripts/extract.py <file_path> [--mode no_ai|groq|local|gemini|openai] [--pretty/--compact]
```

## Options
- `file_path`: Path to PDF or image file (`.pdf`, `.jpg`, `.png`).
- `--mode`: AI backend to invoke. Defaults to `AI_MODE` in `.env`.
- `--save`: Automatically writes JSON payload to `outputs/<doc_id>.json`.

## Standard Output
The extracted data is formatted strictly as:

```json
{
  "is_invoice": true,
  "vendor": "Northwind Logistics Ltd",
  "invoice_number": "NWL-88213",
  "invoice_date": "2026-04-08",
  "currency": "GBP",
  "line_items": [
    {
      "description": "Pallet freight, Manchester to Glasgow",
      "quantity": 3.0,
      "amount": 435.0
    }
  ],
  "tax_total": 113.9,
  "total": 683.4
}
```
