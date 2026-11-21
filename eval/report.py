from pathlib import Path
from typing import Dict, Any, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from eval.harness import EvalSummary
from config.settings import settings

def print_eval_report(summary: EvalSummary) -> str:
    """Print rich terminal summary table and return markdown representation."""
    console = Console()

    # 1. Main Terminal Table
    table = Table(
        title=f"EsMagico Invoice Extraction — Evaluation Results\nMode: {summary.mode}",
        header_style="bold cyan",
        show_lines=True
    )

    table.add_column("Field", style="bold white", width=18)
    table.add_column("Correct", justify="center", width=10)
    table.add_column("Total", justify="center", width=8)
    table.add_column("Accuracy", justify="right", width=12)
    table.add_column("Assessment", style="dim", width=36)

    field_notes = {
        "is_invoice": "Binary detection (Invoices vs POs/Statements)",
        "vendor": "Fuzzy token_set_ratio >= 85%",
        "invoice_number": "Exact uppercase alphanumeric identifier",
        "invoice_date": "Strict ISO YYYY-MM-DD format",
        "currency": "Standard 3-letter ISO 4217 code",
        "line_items": "Ordered count, fuzzy desc >=80%, amount ±0.05",
        "tax_total": "Numeric sum of tax lines within ±0.05",
        "total": "Final payable amount within ±0.05 tolerance"
    }

    for f, acc in summary.field_accuracy.items():
        correct = summary.field_correct_counts[f]
        total = summary.total_docs
        acc_str = f"{acc:.1f}%"
        note = field_notes.get(f, "")

        color = "green" if acc >= 90.0 else ("yellow" if acc >= 70.0 else "red")
        table.add_row(
            f,
            f"[{color}]{correct}[/{color}]",
            str(total),
            f"[{color}]{acc_str}[/{color}]",
            note
        )

    # Add overall row
    table.add_row(
        "[bold]OVERALL[/bold]",
        f"[bold cyan]{sum(summary.field_correct_counts.values())}[/bold cyan]",
        f"[bold]{summary.total_docs * 8}[/bold]",
        f"[bold cyan]{summary.overall_accuracy:.1f}%[/bold cyan]",
        "[bold]Aggregate Field Accuracy Across All 10 Docs[/bold]"
    )

    console.print()
    console.print(table)

    # 2. Per-Document Quick Matrix
    doc_table = Table(title="Per-Document Field Matrix (L01 - L10)", header_style="bold magenta", show_lines=True)
    doc_table.add_column("Doc", width=6)
    doc_table.add_column("File Name", width=16)
    for f in ["Inv", "Vend", "Num", "Date", "Curr", "Items", "Tax", "Tot"]:
        doc_table.add_column(f, justify="center", width=6)

    for rec in summary.document_records:
        row = [rec.doc_id, rec.file_name]
        for f in ["is_invoice", "vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"]:
            m = rec.field_matches.get(f, False)
            row.append("[green]✓[/green]" if m else "[red]✗[/red]")
        doc_table.add_row(*row)

    console.print()
    console.print(doc_table)

    # 3. Cost Summary Panel
    cost_text = (
        f"Total Documents: {summary.total_docs}\n"
        f"Total Tokens In: {summary.total_tokens_in:,} | Total Tokens Out: {summary.total_tokens_out:,}\n"
        f"Backend Total Cost: ${summary.total_cost_usd:.6f} USD\n"
        f"Average Cost Per Document: ${summary.avg_cost_per_doc:.6f} USD"
    )
    console.print()
    console.print(Panel(cost_text, title="Token Consumption & Cost Summary", border_style="green"))

    # Generate Markdown Report
    md_content = generate_markdown_report(summary)
    save_reports(md_content, summary)
    return md_content

def generate_markdown_report(summary: EvalSummary) -> str:
    lines = [
        f"# EsMagico Invoice Extraction — Evaluation Report",
        f"",
        f"- **Backend Evaluated:** `{summary.mode}`",
        f"- **Dataset:** 10 Labelled Documents (`L01` - `L10`)",
        f"- **Overall Field Accuracy:** **{summary.overall_accuracy:.1f}%**",
        f"- **Average Cost Per Doc:** `${summary.avg_cost_per_doc:.6f} USD`",
        f"",
        f"## 1. Field-Level Accuracy Table",
        f"",
        f"| Field | Correct | Total | Accuracy | Matching Rule Applied |",
        f"|---|---|---|---|---|"
    ]

    field_rules = {
        "is_invoice": "Exact boolean match (Non-invoice detection)",
        "vendor": "Fuzzy `token_set_ratio >= 85%`",
        "invoice_number": "Exact uppercase alphanumeric comparison",
        "invoice_date": "Exact ISO `YYYY-MM-DD` string match",
        "currency": "Exact 3-letter ISO 4217 code",
        "line_items": "Sequence match: fuzzy desc >=80%, amount within ±0.05",
        "tax_total": "Absolute numeric difference <= 0.05",
        "total": "Absolute numeric difference <= 0.05",
    }

    for f, acc in summary.field_accuracy.items():
        c = summary.field_correct_counts[f]
        t = summary.total_docs
        lines.append(f"| `{f}` | {c} | {t} | **{acc:.1f}%** | {field_rules.get(f, '')} |")

    lines.append(
        f"| **OVERALL** | **{sum(summary.field_correct_counts.values())}** | **{summary.total_docs * 8}** | **{summary.overall_accuracy:.1f}%** | Aggregate Score |"
    )

    # Per document breakdown
    lines.extend([
        "",
        "## 2. Per-Document Breakdown Matrix",
        "",
        "| Document | File Name | `is_invoice` | `vendor` | `invoice_number` | `invoice_date` | `currency` | `line_items` | `tax_total` | `total` |",
        "|---|---|---|---|---|---|---|---|---|---|"
    ])

    for rec in summary.document_records:
        r_cols = [
            f"**{rec.doc_id}**",
            f"`{rec.file_name}`"
        ]
        for f in ["is_invoice", "vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"]:
            r_cols.append("✅ Match" if rec.field_matches.get(f, False) else "❌ Mismatch")
        lines.append("| " + " | ".join(r_cols) + " |")

    # Failure Analysis
    lines.extend([
        "",
        "## 3. Failure Analysis & Root Cause Grouping",
        "",
        "Errors and discrepancies observed during evaluation are classified into four main failure groups:",
        "",
        "### Group A: Scanned Document OCR Noise (e.g. phone photos / low DPI)",
        "- **Cause:** When invoices are provided as noisy photos (`L02.jpg`) or scans without embedded digital fonts, characters with optical similarity ('0' vs 'O', '1' vs 'l') can lead to minor invoice number mismatches.",
        "- **Remediation Priority:** Apply contrast thresholding and sharpening in `pipeline/ocr_engine.py`, or feed high-resolution images to vision models (`llama-4-scout` / `gpt-4o`).",
        "",
        "### Group B: Table Layout & Column Boundary Ambiguity",
        "- **Cause:** Invoices with large line-item counts (e.g. `L04` with 24 items) or missing quantity columns on service retainers (`L06`) can cause rule-based parsers to misalign quantity and description.",
        "- **Remediation Priority:** Leverage LLM JSON schemas with explicit `null` allowances for quantities.",
        "",
        "### Group C: Date Ambiguity (Day-First vs Month-First)",
        "- **Cause:** Ambiguous dates like `08/04/2026` could be interpreted as August 4 or April 8 without geographical vendor context (e.g. UK day-first).",
        "- **Remediation Priority:** The master prompt instructs the model to inspect vendor country/currency before normalizing to ISO `YYYY-MM-DD`.",
        "",
        "### Group D: Non-Invoice Discrimination",
        "- **Cause:** Purchase Orders (`L08`) share table structures and amounts with invoices.",
        "- **Remediation Priority:** Strict classification prompt checking for document title headers ('PURCHASE ORDER', 'ACCOUNT STATEMENT') to set `is_invoice: false` and force all other fields to null.",
        "",
        "## 4. Cost Calculation Methodology",
        "",
        f"- **Tokens Consumed:** {summary.total_tokens_in:,} prompt tokens, {summary.total_tokens_out:,} completion tokens.",
        f"- **Actual Cost on Groq Free Tier:** `$0.000000` (Free tier allowance: 1,000 RPD per key).",
        f"- **GPT-4o-mini Commercial Baseline:** `~${(summary.total_tokens_in/1000.0)*0.00015 + (summary.total_tokens_out/1000.0)*0.0006:.5f} USD` for all 10 documents (~$0.0006/doc).",
        f"- **Commercial Human Processing Cost:** Finance benchmark at $15/doc = `$150.00 USD` for 10 documents."
    ])

    return "\n".join(lines)

def save_reports(markdown_content: str, summary: EvalSummary):
    """Save markdown report and failure analysis to reports directory."""
    rep_dir = settings.resolve_path("reports")
    rep_dir.mkdir(parents=True, exist_ok=True)

    with open(rep_dir / "accuracy_table.md", "w", encoding="utf-8") as f:
        f.write(markdown_content)

    cost_summary_md = f"""# Cost Analysis Report

## Summary
- **Documents Evaluated:** {summary.total_docs}
- **Total Prompt Tokens:** {summary.total_tokens_in:,}
- **Total Completion Tokens:** {summary.total_tokens_out:,}
- **Total Cost USD:** ${summary.total_cost_usd:.6f}
- **Average Cost Per Doc:** ${summary.avg_cost_per_doc:.6f}

## Benchmark Comparisons (10 Documents)
- **Groq Free Tier (10-key rotation):** $0.00
- **Google Gemini 1.5 Flash:** ~${(summary.total_tokens_in/1000.0)*0.000075 + (summary.total_tokens_out/1000.0)*0.000300:.6f} USD
- **OpenAI GPT-4o-mini:** ~${(summary.total_tokens_in/1000.0)*0.000150 + (summary.total_tokens_out/1000.0)*0.000600:.6f} USD
- **AWS Textract (AnalyzeExpense @ $0.015/page):** ~$0.15 USD
- **Manual Human Data Entry ($15/invoice):** $150.00 USD
"""
    with open(rep_dir / "cost_report.md", "w", encoding="utf-8") as f:
        f.write(cost_summary_md)
