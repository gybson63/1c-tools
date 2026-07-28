"""Vendored helpers adapted from Nikolay-Shirokov/cc-1c-skills."""

from __future__ import annotations

import threading

# Serializes temporary sys.argv mutations in CLI-style vendor entrypoints.
ARGV_LOCK = threading.Lock()
