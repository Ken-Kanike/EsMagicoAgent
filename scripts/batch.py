#!/usr/bin/env python3
import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.extractor import InvoiceExtractor
from pipeline.output_writer import write_output
from ai_backends.router import get_backend
from config.settings import settings

app = typer.Typer(help="Batch process a folder of documents and generate output JSON files.")
console = Console()

@app.command()
def batch(
    folder_path: Path = typer.Argument(..., help="Path to directory containing invoice files."),
    mode: str = typer.Option(None, "--mode", "-m", help="AI backend mode to use."),
    output_dir: Path = typer.Option(None, "--output-dir", "-o", help="Target output directory.")
):
    if not folder_path.exists() or not folder_path.is_dir():
        console.print(f"[red]Error: Invalid directory: {folder_path}[/red]")
        sys.exit(1)

    out_dir = output_dir or settings.resolve_path(settings.outputs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = get_backend(mode)
    extractor = InvoiceExtractor(backend)

    # Collect supported files (.pdf, .jpg, .png, etc.)
    extensions = ("*.pdf", "*.jpg", "*.jpeg", "*.png", "*.webp")
    files = []
    for ext in extensions:
        files.extend(list(folder_path.glob(ext)))
    files = sorted(set(files))

    if not files:
        console.print(f"[yellow]No supported document files found in: {folder_path}[/yellow]")
        sys.exit(0)

    console.print(f"[bold cyan]Batch Processing {len(files)} documents using backend: {backend.name}[/bold cyan]")

    table = Table(title="Batch Processing Results", show_lines=True)
    table.add_column("File", style="bold white", width=16)
    table.add_column("Is Invoice", justify="center", width=12)
    table.add_column("Vendor", width=24)
    table.add_column("Total", justify="right", width=12)
    table.add_column("Status", justify="center", width=14)

    success_count = 0
    flagged_count = 0

    for file_path in files:
        result = extractor.extract(file_path)
        pred = result.data or {}

        # Save output JSON
        if pred:
            write_output(file_path.stem, pred, output_dir=out_dir)

        is_inv = pred.get("is_invoice", False)
        vendor = str(pred.get("vendor") or "—")[:22]
        tot_val = pred.get("total")
        tot_str = f"{tot_val:.2f}" if tot_val is not None else "—"

        if result.needs_review:
            status = "[yellow]Needs Review[/yellow]"
            flagged_count += 1
        elif result.error:
            status = "[red]Error[/red]"
        else:
            status = "[green]Valid[/green]"
            success_count += 1

        inv_str = "[green]Yes[/green]" if is_inv else "[blue]No[/blue]"
        table.add_row(file_path.name, inv_str, vendor, tot_str, status)

    console.print()
    console.print(table)
    console.print(f"\n[bold green]Complete![/bold green] Successfully processed {len(files)} files.")
    console.print(f"Valid: {success_count} | Flagged for Review: {flagged_count}")
    console.print(f"Outputs written to: {out_dir}")

if __name__ == "__main__":
    app()
