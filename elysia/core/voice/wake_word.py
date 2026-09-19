"""Wake Word Detection providers and abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable
import threading


@dataclass
class WakeWordResult:
    """Result of wake word detection."""
    detected: bool
    keyword: str
    confidence: float
    timestamp: float
    audio_context: Optional[bytes] = None


class WakeWordProvider(ABC):
    """Abstract base class for wake word detection providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_keywords(self) -> List[str]:
        pass

    @abstractmethod
    def detect(self, audio_data: bytes, sample_rate: int = 16000) -> WakeWordResult:
        """Detect wake word in audio data."""
        pass

    @abstractmethod
    def start_listening(self, keywords: List[str] = None,
                        callback: Callable[[WakeWordResult], None] = None) -> "WakeWordListener":
        """Start continuous wake word listening."""
        pass

    def is_available(self) -> bool:
        return True


class WakeWordListener:
    """Handles continuous wake word listening."""

    def __init__(self, provider: WakeWordProvider):
        self.provider = provider
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[WakeWordResult], None]] = None

    def start(self, keywords: List[str] = None,
              callback: Callable[[WakeWordResult], None] = None):
        self._running = True
        self._callback = callback
        # Implementation would start provider's listening loop

    def stop(self):
        self._running = False


class WakeWordDetector:
    """High-level wake word detection interface."""

    def __init__(self):
        self._providers: Dict[str, WakeWordProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: WakeWordProvider, default: bool = False):
        self._providers[provider.name] = provider
        if default or not self._default:
            self._default = provider.name

    def detect(self, audio_data: bytes, sample_rate: int = 16000,
               keywords: List[str] = None, provider: str = None) -> "WakeWordResult":
        provider_name = provider or self._default
        if not provider_name:
            raise ValueError("No wake word provider available")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown wake word provider: {provider_name}")
        return provider.detect(audio_data, sample_rate)

    def start_listening(self, keywords: List[str] = None,
                        callback: Callable[["WakeWordResult"], None] = None,
                        provider: str = None) -> "WakeWordListener":
        provider_name = provider or self._default
        if not provider_name:
            raise ValueError("No wake word provider available")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown wake word provider: {provider_name}")
        return provider.start_listening(keywords, callback)

    def get_provider(self, name: str):
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())


from typing import Optional, List, Dict, Any, Callable