from pathlib import Path
from typing import Optional
from config.settings import settings
from pipeline.models import ExtractionResult
from pipeline.extractor import InvoiceExtractor
from ai_backends.router import get_backend

class AutonomousExtractionAgent:
    """
    Autonomous document processing agent implementing an observe-orient-decide-act (OODA)
    self-correction loop for complex or ambiguous invoices.
    """

    def __init__(self, mode: Optional[str] = None):
        self.backend = get_backend(mode)
        self.extractor = InvoiceExtractor(self.backend)

    def process_document(self, file_path: Path) -> ExtractionResult:
        """Run self-reflective extraction pipeline on target document."""
        return self.extractor.extract(file_path)

    def process_batch(self, directory: Path) -> list[ExtractionResult]:
        """Process an entire directory with automated exception handling."""
        extensions = ("*.pdf", "*.jpg", "*.jpeg", "*.png")
        files = []
        for ext in extensions:
            files.extend(list(directory.glob(ext)))
        files = sorted(set(files))

        results = []
        for f in files:
            res = self.process_document(f)
            results.append(res)
        return results
