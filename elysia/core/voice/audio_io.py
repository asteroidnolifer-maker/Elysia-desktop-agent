"""Audio I/O abstraction for input/output devices."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any, Iterator
import threading
import queue


class AudioFormat(Enum):
    PCM16 = "pcm16"
    PCM24 = "pcm24"
    PCM32 = "pcm32"
    FLOAT32 = "float32"


@dataclass
class AudioDevice:
    """Represents an audio input/output device."""
    id: str
    name: str
    is_input: bool
    is_output: bool
    max_channels: int
    default_sample_rate: int
    supported_formats: List[AudioFormat]
    is_default_input: bool = False
    is_default_output: bool = False


class AudioInput(ABC):
    """Abstract audio input device."""

    @property
    @abstractmethod
    def device(self) -> AudioDevice:
        pass

    @abstractmethod
    def start(self, sample_rate: int = 16000, channels: int = 1,
              format: AudioFormat = AudioFormat.PCM16) -> None:
        pass

    @abstractmethod
    def read(self, frames: int) -> bytes:
        """Read audio data."""
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def is_active(self) -> bool:
        pass


class AudioOutput(ABC):
    """Abstract audio output device."""

    @property
    @abstractmethod
    def device(self) -> AudioDevice:
        pass

    @abstractmethod
    def start(self, sample_rate: int = 16000, channels: int = 1,
              format: AudioFormat = AudioFormat.PCM16) -> None:
        pass

    @abstractmethod
    def write(self, data: bytes) -> int:
        """Write audio data. Returns number of frames written."""
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_latency(self) -> float:
        """Get output latency in seconds."""
        pass


class AudioDeviceManager:
    """Manages audio input/output devices."""

    def __init__(self):
        self._input_devices: Dict[str, AudioInput] = {}
        self._output_devices: Dict[str, AudioOutput] = {}
        self._default_input: Optional[str] = None
        self._default_output: Optional[str] = None

    def register_input(self, device: AudioInput, default: bool = False):
        self._input_devices[device.device.id] = device
        if default or not self._default_input:
            self._default_input = device.device.id

    def register_output(self, device: AudioOutput, default: bool = False):
        self._output_devices[device.device.id] = device
        if default or not self._default_output:
            self._default_output = device.device.id

    def get_input(self, device_id: str = None) -> Optional[AudioInput]:
        if device_id:
            return self._input_devices.get(device_id)
        return self._input_devices.get(self._default_input) if self._default_input else None

    def get_output(self, device_id: str = None) -> Optional[AudioOutput]:
        if device_id:
            return self._output_devices.get(device_id)
        return self._output_devices.get(self._default_output) if self._default_output else None

    def list_inputs(self) -> List[AudioDevice]:
        return [d.device for d in self._input_devices.values()]

    def list_outputs(self) -> List[AudioDevice]:
        return [d.device for d in self._output_devices.values()]


from typing import Optional, List, Dict, Any