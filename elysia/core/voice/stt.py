"""Speech-to-Text providers and abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import threading
import queue


@dataclass
class TranscriptionResult:
    """Result of speech-to-text transcription."""
    text: str
    confidence: float
    language: str = "en"
    duration_ms: float = 0.0
    is_final: bool = True
    metadata: Dict[str, Any] = None


class SpeechToTextProvider(ABC):
    """Abstract base class for STT providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        pass

    @property
    @abstractmethod
    def supported_languages(self) -> List[str]:
        pass

    @abstractmethod
    def transcribe(self, audio_data: bytes, sample_rate: int = 16000,
                   language: str = "en") -> TranscriptionResult:
        """Transcribe audio data to text."""
        pass

    @abstractmethod
    def start_streaming(self, sample_rate: int = 16000,
                        language: str = "en") -> "StreamingTranscriber":
        """Start a streaming transcription session."""
        pass

    def is_available(self) -> bool:
        """Check if the provider is available."""
        return True


class StreamingTranscriber:
    """Handles streaming transcription."""

    def __init__(self, provider: SpeechToTextProvider):
        self.provider = provider
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._results: queue.Queue[TranscriptionResult] = queue.Queue()
        self._running = False
        self._thread: threading.Thread = None

    def push_audio(self, audio_chunk: bytes):
        """Push audio data to the stream."""
        self._queue.put(audio_chunk)

    def get_result(self, timeout: float = 0.1) -> Optional[TranscriptionResult]:
        """Get the next transcription result."""
        try:
            return self._results.get(timeout=timeout)
        except queue.Empty:
            return None

    def start(self):
        """Start the transcription thread."""
        self._running = True
        # Implementation would start the provider's streaming API

    def stop(self):
        """Stop the transcription."""
        self._running = False


class SpeechToText:
    """High-level STT interface with provider management."""

    def __init__(self):
        self._providers: Dict[str, SpeechToTextProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: SpeechToTextProvider, default: bool = False):
        self._providers[provider.name] = provider
        if default or not self._default:
            self._default = provider.name

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000,
                   language: str = "en", provider: str = None) -> TranscriptionResult:
        provider_name = provider or self._default
        if not provider_name:
            raise ValueError("No STT provider available")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown STT provider: {provider_name}")
        return provider.transcribe(audio_data, sample_rate, language)

    def get_provider(self, name: str):
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())


from typing import Optional, List, Dict, Any