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
# The canonical module's _manager() function checks this module's _manager_override
# Tests can do: `with mock.patch.object(brain, "_manager_override", pm):`
# or `with mock.patch.object(brain, "_manager", pm):` if we also sync

# Make _manager a simple module variable that tests can patch
# When set, also update the canonical module's override
_manager = None

# Legacy _manager_override for tests that patch it directly
# This is what the canonical _manager() function checks
_manager_override = None

# Re-export canonical functions
from elysia.core.brain import (
    SYSTEM_PROMPT,
    chat,
    chat_style,
    parse_file_blocks,
    qa_check,
    health,
)

# Re-export _manager_override for tests that patch it directly
from elysia.core.brain import _manager_override

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