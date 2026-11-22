#!/usr/bin/env python3
"""
Process every PDF/image in one or more folders in parallel and write outputs/<name>.json.

    python scripts/batch.py "Es Magico - AI Intern Assignment - Sample Pack/unlabelled"
    python scripts/batch.py "Es Magico - AI Intern Assignment - Sample Pack/labelled" "...unlabelled"   # all 20
"""
import logging
import sys
import time
import warnings
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TimeElapsedColumn
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore", category=FutureWarning)

from ai_backends.base import BackendNotConfigured  # noqa: E402
from ai_backends.router import get_backend  # noqa: E402
from config.settings import settings  # noqa: E402
from pipeline.batch_runner import collect_files, run_many  # noqa: E402
from pipeline.extractor import InvoiceExtractor  # noqa: E402
from pipeline.output_writer import write_output, write_run_metadata  # noqa: E402

app = typer.Typer(add_completion=False)


@app.command()
def batch(
    folders: List[Path] = typer.Argument(..., help="One or more folders of documents"),
    mode: str = typer.Option(None, "--mode", "-m"),
    output_dir: Path = typer.Option(None, "--output-dir", "-o"),
    workers: int = typer.Option(None, "--workers", "-w"),
    cache: bool = typer.Option(True, "--cache/--no-cache"),
):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    console = Console(legacy_windows=False)
    files: List[Path] = []
    for folder in folders:
        if not folder.is_dir():
            console.print(f"[red]Not a directory: {folder}[/red]")
            raise typer.Exit(1)
        files += collect_files(folder)
    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        raise typer.Exit(0)

    try:
        extractor = InvoiceExtractor(get_backend(mode), use_cache=cache)
    except BackendNotConfigured as e:
        console.print(f"[red]ERROR: {e}[/red]")
        raise typer.Exit(2)

    out_dir = output_dir or settings.resolve_path(settings.outputs_dir)
    console.print(f"[bold cyan]{len(files)} documents | backend: {extractor.backend.name} | "
                  f"workers: {workers or settings.max_workers}[/bold cyan]")
    t0 = time.time()
    with Progress("[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
                  TimeElapsedColumn(), console=console) as prog:
        task = prog.add_task("extracting", total=len(files))
        results = run_many(files, extractor, workers=workers,
                           on_progress=lambda done, total, r: prog.update(task, completed=done,
                                                                          description=f"last: {r.file}"))
    wall = time.time() - t0

    table = Table(title="Batch results", show_lines=False)
    for c in ("File", "Invoice", "Vendor", "Total", "Status", "Calls", "Sec"):
        table.add_column(c)
    n_ok = n_flag = n_err = 0
    tok_in = tok_out = 0
    cost = 0.0
    for p, r in zip(files, results):
        if r.data:
            write_output(p.stem, r.data, output_dir=out_dir)
        if r.cost:
            tok_in += r.cost.tokens_in
            tok_out += r.cost.tokens_out
            cost += r.cost.cost_usd
        if r.error:
            status, n_err = f"[red]error: {r.error_type}[/red]", n_err + 1
        elif r.needs_review:
            status, n_flag = "[yellow]needs review[/yellow]", n_flag + 1
        else:
            status, n_ok = "[green]valid[/green]", n_ok + 1
        d = r.data or {}
        total = d.get("total")
        table.add_row(p.name, "yes" if d.get("is_invoice") else ("no" if d else "-"),
                      str(d.get("vendor") or "-")[:28], f"{total:,.2f}" if isinstance(total, (int, float)) else "-",
                      status, str(r.cost.calls if r.cost else 0), f"{r.elapsed_s:.1f}")
    console.print(table)
    meta = write_run_metadata(results, "batch_run_metadata")
    console.print(f"valid {n_ok} | needs review {n_flag} | errors {n_err} | wall {wall:.1f}s | "
                  f"tokens {tok_in:,} in / {tok_out:,} out | list-price cost ${cost:.5f}")
    console.print(f"outputs -> {out_dir}   review flags & costs -> {meta}")


if __name__ == "__main__":
    app()
