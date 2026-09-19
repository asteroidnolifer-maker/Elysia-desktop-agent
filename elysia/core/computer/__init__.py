"""Elysia Computer Control — structured desktop automation with permissions."""
from .controller import ComputerController, MouseController, KeyboardController
from .screen import ScreenCapture, ScreenRegion
from .vision import VisionPipeline
from .permissions import ComputerPermissions, ComputerAction
from .legacy import Computer, DesktopBackend, NullDesktop, CommandLineDesktop

__all__ = [
    "ComputerController",
    "MouseController",
    "KeyboardController",
    "ScreenCapture",
    "ScreenRegion",
    "VisionPipeline",
    "ComputerPermissions",
    "ComputerAction",
    "Computer",
    "DesktopBackend",
    "NullDesktop",
    "CommandLineDesktop",
]