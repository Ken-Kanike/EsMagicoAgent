#!/usr/bin/env python3
import sys
from pathlib import Path
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.harness import run_evaluation
from eval.report import print_eval_report
from config.settings import settings

app = typer.Typer(help="Execute evaluation harness against ground truth labelled documents.")

@app.command()
def main(
    mode: str = typer.Option(None, "--mode", "-m", help="AI backend mode (default: from .env)."),
    data_dir: Path = typer.Option(None, "--data-dir", "-d", help="Path to labelled directory.")
):
    target_dir = data_dir or settings.resolve_path(settings.labelled_dir)
    print(f"Starting evaluation harness using directory: {target_dir}")
    print(f"Resolving backend: {mode or settings.ai_mode}...")

    summary = run_evaluation(mode=mode, labelled_dir=target_dir, save_outputs=True)
    print_eval_report(summary)

if __name__ == "__main__":
    app()
