"""Parallel document processing shared by the CLI batch, the eval harness and the API job queue."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from config.settings import settings
from pipeline.extractor import InvoiceExtractor
from pipeline.models import ExtractionResult

ProgressFn = Callable[[int, int, ExtractionResult], None]


def run_many(paths: Sequence[Path], extractor: InvoiceExtractor, workers: Optional[int] = None,
             on_progress: Optional[ProgressFn] = None) -> List[ExtractionResult]:
    """
    Extract many documents concurrently (I/O-bound LLM calls). Results keep input order.
    One failing document never stops the batch (extract() never raises).
    The Groq backend's shared token bucket keeps concurrent workers inside the rate limit.
    """
    paths = list(paths)
    workers = max(1, min(workers or settings.max_workers, len(paths) or 1))
    results: List[Optional[ExtractionResult]] = [None] * len(paths)
    if workers == 1:
        for i, p in enumerate(paths):
            results[i] = extractor.extract(p)
            if on_progress:
                on_progress(i + 1, len(paths), results[i])
        return results  # type: ignore[return-value]

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(extractor.extract, p): i for i, p in enumerate(paths)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # defensive: extract() should not raise
                results[i] = ExtractionResult.error_result(paths[i].name, f"{type(e).__name__}: {e}", "internal_error")
            done += 1
            if on_progress:
                on_progress(done, len(paths), results[i])
    return results  # type: ignore[return-value]


def collect_files(folder: Path) -> List[Path]:
    from pipeline.document_loader import SUPPORTED_SUFFIXES
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
