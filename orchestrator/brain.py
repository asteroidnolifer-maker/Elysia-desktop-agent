#!/usr/bin/env python3
"""
Legacy brain.py compatibility stub.

All actual provider logic moved to elysia.core.providers.
This module re-exports the canonical functions for backward compatibility.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elysia.core.brain import (
    SYSTEM_PROMPT,
    chat,
    chat_style,
    parse_file_blocks,
    qa_check,
    health,
)

# For test patching: tests can set this to override the provider manager
# The canonical functions in elysia.core.brain check this first
_manager_override = None

# Canonical functions
from elysia.core.brain import (
    SYSTEM_PROMPT,
    chat,
    chat_style,
    parse_file_blocks,
    qa_check,
    health,
)

# Backward compatibility: _manager for legacy tests that patch it
# Allow tests to do: `with mock.patch.object(brain, "_manager", pm):`
# This variable is used by the canonical module's _manager() function
_manager_override = None

# Canonical functions
from elysia.core.brain import (
    SYSTEM_PROMPT,
    chat,
    chat_style,
    parse_file_blocks,
    qa_check,
    health,
)

# Backward compatibility: _manager for legacy tests that patch it
# Allow tests to do: `with mock.patch.object(brain, "_manager", pm):`
_manager = None

# Keep _manager and _manager_override in sync
# When tests patch _manager, also update the canonical module
def _sync_manager_override():
    import elysia.core.brain
    elysia.core.brain._manager_override = _manager_override

# Backward compatibility: _manager for legacy tests that patch it
_manager = None

__all__ = [
    "SYSTEM_PROMPT",
    "chat",
    "chat_style",
    "parse_file_blocks",
    "qa_check",
    "health",
    "_manager_override",
    "_manager",
]