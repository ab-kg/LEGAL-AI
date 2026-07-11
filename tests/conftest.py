"""
Shared Test Fixtures
=====================
Centralised setup for all test files:
  - IPv4-only socket patch (runs once at import time)
  - Helper functions for credential checks
"""

import os
import sys

# Ensure project root is on sys.path so ``src.core`` is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Apply the IPv4 patch once for all tests
from src.core.common.utils import force_ipv4
force_ipv4()


def has_gemini_key():
    """Return True if a Gemini API key is available."""
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def has_groq_key():
    """Return True if a Groq API key is available."""
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def has_mongo_uri():
    """Return True if a MongoDB URI is available."""
    return bool(os.getenv("MONGO_URI", "").strip())


def get_active_provider():
    """Return the active LLM provider name."""
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower()


def get_active_model_name():
    """Return a human-readable model name for the active provider."""
    provider = get_active_provider()
    if provider == "gemini":
        return f"gemini-2.5-flash (Gemini)"
    return f"llama-3.1-8b-instant (Groq)"
