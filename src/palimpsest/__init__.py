"""Palimpsest — a production-grade agent memory layer on CockroachDB.

New knowledge layers over old; history is never destroyed.
"""

__version__ = "0.1.0"

from .config import Settings, settings
from .engine.memory import MemoryEngine

__all__ = ["Settings", "settings", "MemoryEngine", "__version__"]
