"""Voice Pipeline — orchestrates STT, Wake Word, TTS, and Audio I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable
import threading
import time
import uuid

from .stt import SpeechToText, TranscriptionResult
from .tts import TextToSpeech, SynthesisResult
from .wake_word import WakeWordDetector, WakeWordResult
from .audio_io import AudioInput, AudioOutput, AudioDeviceManager


class VoiceState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    WAKE_DETECTED = "wake_detected"
    CAPTURING = "capturing"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ACTING = "acting"
    VERIFYING = "verifying"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class VoiceEvent:
    """Event in the voice pipeline."""
    event_type: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""


class VoicePipeline:
    """Orchestrates the complete voice interaction pipeline."""

    def __init__(self, audio_manager: AudioDeviceManager,
                 stt: SpeechToText, tts: TextToSpeech,
                 wake_word: Optional[Any] = None):
        self.audio = audio_manager
        self.stt = stt
        self.tts = tts
        self.wake_word = wake_word
        self._state = VoiceState.IDLE
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[VoiceEvent], None]] = []
        self._session_id = ""
        self._current_input: Optional[AudioInput] = None
        self._current_output: Optional[AudioOutput] = None
        self._wake_listener = None
        self._stt_stream = None

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    def _set_state(self, state: VoiceState):
        with self._lock:
            old = self._state
            self._state = state
            self._emit(VoiceEvent("state_changed", data={"from": old.value, "to": state.value}))

    def _emit(self, event: VoiceEvent):
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def on_event(self, callback: Callable[[VoiceEvent], None]):
        self._callbacks.append(callback)

    def start_session(self) -> str:
        """Start a new voice interaction session."""
        self._session_id = f"session-{uuid.uuid4().hex[:8]}"
        self._set_state(VoiceState.IDLE)
        self._emit(VoiceEvent("session_started", session_id=self._session_id))
        return self._session_id

    def end_session(self):
        """End the current voice session."""
        self.stop_listening()
        self.stop_speaking()
        self._emit(VoiceEvent("session_ended", session_id=self._session_id))
        self._session_id = ""

    def start_listening(self, wake_word: bool = True,
                        continuous: bool = False,
                        sample_rate: int = 16000,
                        input_device: str = None) -> str:
        """Start listening for voice input."""
        if self._state != VoiceState.IDLE:
            raise RuntimeError(f"Cannot listen in state {self._state.value}")

        self._set_state(VoiceState.LISTENING)

        # Get input device
        self._current_input = self.audio.get_input()
        if not self._current_input:
            self._set_state(VoiceState.ERROR)
            raise RuntimeError("No audio input device available")

        self._current_input.start()

        if wake_word and self.wake_word:
            self._set_state(VoiceState.LISTENING)
            self._wake_listener = self.wake_word.start_listening(
                callback=self._on_wake_word
            )
        else:
            # Direct transcription mode
            self._set_state(VoiceState.CAPTURING)
            self._start_transcription(sample_rate)

        return str(uuid.uuid4())

    def _on_wake_word(self, result):
        """Callback when wake word is detected."""
        self._set_state(VoiceState.WAKE_DETECTED)
        self._emit(VoiceEvent("wake_detected", data={"keyword": result.keyword, "confidence": result.confidence}))
        # Start capturing speech after wake word
        self._start_transcription()

    def _start_transcription(self, sample_rate: int = 16000):
        self._set_state(VoiceState.TRANSCRIBING)
        # Start STT streaming
        self._stt_stream = self.stt._providers[list(self.stt._providers.keys())[0]].start_streaming()
        # Audio capture loop would run in separate thread
        # For now, this is a placeholder

    def stop_listening(self):
        """Stop listening for voice input."""
        if self._wake_listener:
            self._wake_listener.stop()
            self._wake_listener = None
        if self._stt_stream:
            self._stt_stream.stop()
            self._stt_stream = None
        if self._current_input:
            self._current_input.stop()
            self._current_input = None
        if self._state in (VoiceState.LISTENING, VoiceState.CAPTURING, VoiceState.TRANSCRIBING, VoiceState.WAKE_DETECTED):
            self._set_state(VoiceState.IDLE)

    def speak(self, text: str, voice: str = None, language: str = "en",
              speed: float = 1.0, wait: bool = True) -> SynthesisResult:
        """Speak text via TTS."""
        self._set_state(VoiceState.SPEAKING)
        self._emit(VoiceEvent("speech_started", data={"text": text[:100]}))

        result = self.tts.synthesize(text, voice=voice, language=language, speed=speed)

        # Play audio (simplified - would use audio output device)
        self._play_audio(result.audio_data, result.sample_rate)

        self._set_state(VoiceState.IDLE)
        self._emit(VoiceEvent("speech_ended", data={"duration_ms": result.duration_ms}))
        return result

    def _play_audio(self, audio_data: bytes, sample_rate: int):
        """Play audio through output device."""
        output = self.audio.get_output()
        if output:
            output.start(sample_rate=sample_rate)
            output.write(audio_data)
            output.stop()

    def stop_speaking(self):
        """Stop current speech."""
        # Would stop TTS playback
        if self._state == VoiceState.SPEAKING:
            self._set_state(VoiceState.IDLE)

    def process_voice_command(self, timeout: float = 30.0) -> Optional[TranscriptionResult]:
        """Listen for a voice command and return transcription."""
        # This would combine wake word + STT in one call
        # Placeholder for full implementation
        return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self._state.value,
            "session_id": self._session_id,
            "has_input": self._current_input is not None,
            "has_output": self._current_output is not None,
        }


import threading
import time
import uuid