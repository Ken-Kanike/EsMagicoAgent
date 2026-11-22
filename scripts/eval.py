#!/usr/bin/env python3
"""One-command evaluation on the 10 labelled documents:  python scripts/eval.py"""
import logging
import sys
import warnings
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore", category=FutureWarning)

from ai_backends.base import BackendNotConfigured  # noqa: E402
from config.settings import settings  # noqa: E402
from eval.harness import run_evaluation  # noqa: E402
from eval.report import print_eval_report  # noqa: E402

app = typer.Typer(add_completion=False, help="Evaluate the extractor against the labelled ground truth.")


@app.command()
def main(
    mode: str = typer.Option(None, "--mode", "-m", help="groq | no_ai | openai | gemini | local (default: AI_MODE)"),
    data_dir: Path = typer.Option(None, "--data-dir", "-d", help="Folder with Lxx.<pdf|jpg> + Lxx.json"),
    workers: int = typer.Option(None, "--workers", "-w", help="Parallel documents (default: MAX_WORKERS)"),
    cache: bool = typer.Option(False, "--cache/--no-cache", help="Reuse cached results (default: fresh run)"),
    no_save: bool = typer.Option(False, "--no-save", help="Do not overwrite outputs/Lxx.json or reports/"),
):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    target = data_dir or settings.resolve_path(settings.labelled_dir)
    print(f"Evaluating {target} with backend '{mode or settings.ai_mode}' (cache={'on' if cache else 'off'})...",
          file=sys.stderr)
    try:
        summary = run_evaluation(mode=mode, labelled_dir=target, save_outputs=not no_save,
                                 use_cache=cache, workers=workers)
    except BackendNotConfigured as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise typer.Exit(2)
    print_eval_report(summary, save=not no_save)


if __name__ == "__main__":
    app()
