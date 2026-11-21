from abc import ABC, abstractmethod
from typing import List, Tuple
from PIL import Image
from pipeline.models import TokenUsage

class AIBackend(ABC):
    """Abstract interface defining required behavior for all extraction backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name of the backend."""
        pass

    @property
    @abstractmethod
    def supports_vision(self) -> bool:
        """Indicates if the backend can consume raw images directly."""
        pass

    @abstractmethod
    def extract(
        self,
        text: str,
        images: List[Image.Image],
        retry: bool = False,
        retry_reason: str = ""
    ) -> Tuple[str, TokenUsage]:
        """
        Execute invoice extraction.
        Returns:
            Tuple[str, TokenUsage]: (raw_json_string, token_usage_record)
        """
        pass
