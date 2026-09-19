"""Camera device abstraction and management."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any, Iterator
import threading


class CameraBackend(Enum):
    V4L2 = "v4l2"
    AVF = "avf"  # macOS
    DSHOW = "dshow"  # Windows
    GSTREAMER = "gstreamer"


@dataclass
class CameraDevice:
    """Represents a camera device."""
    id: str
    name: str
    backend: CameraBackend
    max_resolution: tuple[int, int]
    supported_formats: List[str]
    supported_fps: List[int]
    is_default: bool = False
    capabilities: List[str] = None  # e.g., "auto_focus", "zoom", "pan_tilt"


class Camera(ABC):
    """Abstract camera interface."""

    @property
    @abstractmethod
    def device(self) -> 'CameraDevice':
        pass

    @abstractmethod
    def start(self, resolution: tuple[int, int] = (1280, 720),
              fps: int = 30, format: str = "MJPG") -> None:
        pass

    @abstractmethod
    def capture_frame(self) -> bytes:
        """Capture a single frame as encoded image bytes (JPEG/PNG)."""
        pass

    @abstractmethod
    def capture_raw(self) -> bytes:
        """Capture raw frame data."""
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @property
    @abstractmethod
    def is_active(self) -> bool:
        pass

    @abstractmethod
    def get_properties(self) -> Dict[str, Any]:
        """Get current camera properties (brightness, contrast, etc.)."""
        pass

    @abstractmethod
    def set_property(self, prop: str, value: Any) -> bool:
        """Set a camera property."""
        pass


class CameraManager:
    """Manages camera devices."""

    def __init__(self):
        self._cameras: Dict[str, Camera] = {}
        self._devices: List['CameraDevice'] = []
        self._default_camera: Optional[str] = None
        self._lock = threading.Lock()

    def discover(self) -> List['CameraDevice']:
        """Discover available cameras."""
        # This would use platform-specific backends
        # For now, returns empty list
        return self._devices

    def register(self, camera: 'Camera', default: bool = False):
        with self._lock:
            self._cameras[camera.device.id] = camera
            if default or not self._default_camera:
                self._default_camera = camera.device.id

    def get_camera(self, camera_id: str = None) -> Optional['Camera']:
        if camera_id:
            return self._cameras.get(camera_id)
        if self._default_camera:
            return self._cameras.get(self._default_camera)
        return next(iter(self._cameras.values())) if self._cameras else None

    def list_cameras(self) -> List['CameraDevice']:
        return [c.device for c in self._cameras.values()]

    def release(self, camera_id: str):
        with self._lock:
            if camera_id in self._cameras:
                self._cameras[camera_id].stop()
                del self._cameras[camera_id]
                if self._default_camera == camera_id:
                    self._default_camera = next(iter(self._cameras)) if self._cameras else None


from typing import Optional, List, Dict, Any
import threading