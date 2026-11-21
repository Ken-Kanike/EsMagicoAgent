#!/usr/bin/env python3
import sys
import json
from pathlib import Path
import typer
from rich.console import Console

# Add parent directory to sys.path so scripts can be run directly from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.extractor import InvoiceExtractor
from pipeline.output_writer import write_output
from ai_backends.router import get_backend

app = typer.Typer(help="Extract structured invoice JSON from PDF or image documents.")
console = Console(stderr=True) # Send status logs to stderr so stdout is pure JSON for piping

@app.command()
def extract(
    file_path: Path = typer.Argument(..., help="Path to invoice PDF or image file."),
    mode: str = typer.Option(None, "--mode", "-m", help="AI backend mode (no_ai, groq, local, gemini, openai, antigravity)."),
    save: bool = typer.Option(True, "--save/--no-save", help="Save result to outputs/ directory."),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Pretty-print JSON output.")
):
    if not file_path.exists():
        console.print(f"[red]Error: File not found: {file_path}[/red]")
        sys.exit(1)

    try:
        backend = get_backend(mode)
        extractor = InvoiceExtractor(backend)
        result = extractor.extract(file_path)

        if result.error and not result.data:
            console.print(f"[red]Extraction Error: {result.error}[/red]")
            err_payload = {"error": result.error, "is_invoice": False}
            print(json.dumps(err_payload, indent=2))
            sys.exit(1)

        output_data = result.data or {}

        if save and output_data:
            saved_path = write_output(file_path.stem, output_data)
            console.print(f"[green]Saved output to: {saved_path}[/green]")

        if result.needs_review:
            console.print(f"[yellow]Flagged for review: {', '.join(result.review_reasons)}[/yellow]")

        # Print pure JSON to stdout
        indent_val = 2 if pretty else None
        print(json.dumps(output_data, indent=indent_val, ensure_ascii=False))

    except Exception as e:
        console.print(f"[bold red]Execution Exception: {str(e)}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    app()
