"""OCR providers — text extraction from images."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class OCREngine(Enum):
    TESSERACT = "tesseract"
    EASYOCR = "easyocr"
    PADDLEOCR = "paddleocr"
    GOOGLE_VISION = "google_vision"
    AWS_TEXTRACT = "aws_textract"


@dataclass
class TextRegion:
    """A region of detected text."""
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x, y, w, h normalized 0-1
    language: str = "en"
    orientation: float = 0.0  # degrees


@dataclass
class OCRResult:
    """Result of OCR processing."""
    regions: List[TextRegion] = field(default_factory=list)
    full_text: str = ""
    languages_detected: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "regions": [{"text": r.text, "confidence": r.confidence,
                        "bbox": r.bbox, "language": r.language} for r in self.regions],
            "full_text": self.full_text,
            "languages": self.languages_detected,
            "processing_time_ms": self.processing_time_ms,
        }


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_languages(self) -> List[str]:
        pass

    @property
    @abstractmethod
    def engine(self) -> OCREngine:
        pass

    @abstractmethod
    def extract_text(self, image_data: bytes, languages: List[str] = None,
                     config: Dict[str, Any] = None) -> OCRResult:
        """Extract text from image."""
        pass

    @abstractmethod
    def extract_text_from_regions(self, image_data: bytes,
                                   regions: List[tuple],
                                   languages: List[str] = None) -> OCRResult:
        """Extract text from specific regions."""
        pass

    def is_available(self) -> bool:
        return True


class OCRPipeline:
    """OCR pipeline with multiple provider support."""

    def __init__(self):
        self._providers: Dict[str, OCRProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: 'OCRProvider', default: bool = False):
        self._providers[provider.name] = provider
        if default or not self._default:
            self._default = provider.name

    def extract(self, image_data: bytes, languages: List[str] = None,
                provider: str = None) -> 'OCRResult':
        provider_name = provider or self._default
        if not provider_name:
            raise ValueError("No OCR provider available")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown OCR provider: {provider_name}")
        return provider.extract_text(image_data, languages)

    def get_provider(self, name: str):
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())


from typing import Optional