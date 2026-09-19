"""Vision Pipeline — object detection, classification, scene understanding."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import base64


@dataclass
class DetectedObject:
    """A detected object in an image."""
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x, y, w, h normalized 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionResult:
    """Result of vision analysis."""
    objects: List[DetectedObject] = field(default_factory=list)
    scene_description: str = ""
    tags: List[str] = field(default_factory=list)
    text_content: str = ""
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class VisionProvider(ABC):
    """Abstract base class for vision providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_tasks(self) -> List[str]:
        """Supported tasks: detection, classification, captioning, OCR, etc."""
        pass

    @abstractmethod
    def analyze(self, image_data: bytes, tasks: List[str] = None,
                prompt: str = None) -> 'VisionResult':
        """Analyze an image."""
        pass

    @abstractmethod
    def analyze_batch(self, images: List[bytes],
                      tasks: List[str] = None) -> List['VisionResult']:
        """Analyze multiple images."""
        pass

    def is_available(self) -> bool:
        return True


@dataclass
class VisionResult:
    """Result of vision analysis."""
    objects: List[Any] = field(default_factory=list)
    scene_description: str = ""
    tags: List[str] = field(default_factory=list)
    text_content: str = ""
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class VisionPipeline:
    """Orchestrates vision analysis with multiple providers."""

    def __init__(self):
        self._providers: Dict[str, Any] = {}
        self._default: Optional[str] = None

    def register(self, provider: Any, default: bool = False):
        self._providers[provider.name] = provider
        if default or not self._default:
            self._default = provider.name

    def analyze(self, image_data: bytes, tasks: List[str] = None,
                provider: str = None, prompt: str = None) -> Dict[str, Any]:
        provider_name = provider or self._default
        if not provider_name:
            raise ValueError("No vision provider available")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown vision provider: {provider_name}")
        return provider.analyze(image_data, tasks, prompt)

    def get_provider(self, name: str):
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())