"""Standalone, opt-in evidence collection primitives.

This package deliberately owns only tables whose names begin with ``evidence_``.
"""

from .config import SUPPORTED_PROVIDER_IDS, CollectorSettings, load_settings

__all__ = ["SUPPORTED_PROVIDER_IDS", "CollectorSettings", "load_settings"]
