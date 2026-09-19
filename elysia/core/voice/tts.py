"""Text-to-Speech providers and abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import threading


@dataclass
class SynthesisResult:
    """Result of text-to-speech synthesis."""
    audio_data: bytes
    sample_rate: int
    duration_ms: float
    format: str = "wav"
    metadata: Dict[str, Any] = None


class TextToSpeechProvider(ABC):
    """Abstract base class for TTS providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_voices(self) -> List[Dict[str, Any]]:
        """Return list of available voices with metadata."""
        pass

    @property
    @abstractmethod
    def supported_languages(self) -> List[str]:
        pass

    @abstractmethod
    def synthesize(self, text: str, voice: str = None,
                   language: str = "en", speed: float = 1.0) -> SynthesisResult:
        """Synthesize text to speech."""
        pass

    @abstractmethod
    def start_streaming(self, voice: str = None, language: str = "en") -> "StreamingSynthesizer":
        """Start a streaming synthesis session."""
        pass

    def is_available(self) -> bool:
        return True


class StreamingSynthesizer:
    """Handles streaming TTS synthesis."""

    def __init__(self, provider: TextToSpeechProvider):
        self.provider = provider
        self._running = False

    def push_text(self, text: str):
        """Push text to be synthesized."""
        pass

    def get_audio(self, timeout: float = 0.1) -> Optional[bytes]:
        """Get the next audio chunk."""
        return None

    def start(self):
        self._running = True

    def stop(self):
        self._running = False


class TextToSpeech:
    """High-level TTS interface with provider management."""

    def __init__(self):
        self._providers: Dict[str, TextToSpeechProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: TextToSpeechProvider, default: bool = False):
        self._providers[provider.name] = provider
        if default or not self._default:
            self._default = provider.name

    def synthesize(self, text: str, voice: str = None,
                   language: str = "en", speed: float = 1.0,
                   provider: str = None) -> SynthesisResult:
        provider_name = provider or self._default
        if not provider_name:
            raise ValueError("No TTS provider available")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown TTS provider: {provider_name}")
        return provider.synthesize(text, voice, language, speed)

    def get_provider(self, name: str):
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())


from typing import Optional, List, Dict, Any