"""Elysia Camera System — webcam capture, vision, OCR, object detection."""
from .camera import Camera, CameraDevice, CameraManager
from .vision import VisionProvider, VisionResult, VisionPipeline
from .ocr import OCRProvider, OCRResult

__all__ = [
    "Camera",
    "CameraDevice",
    "CameraManager",
    "VisionProvider",
    "VisionResult",
    "VisionPipeline",
    "OCRProvider",
    "OCRResult",
]