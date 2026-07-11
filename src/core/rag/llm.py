"""
LLM Client Manager
====================
Manages Google Gemini (primary) and Groq (secondary) LLM clients,
including API-key rotation and retry logic for Groq's rate limits,
plus structured 404 error handling for Gemini.
"""

import time
import re
import google.generativeai as genai
from groq import Groq

from src.core.common import config


class LLMManager:
    """Dual-provider LLM client with automatic retry and key rotation."""

    def __init__(self):
        # ── Gemini ──────────────────────────────────────────────────
        self.gemini_enabled = False
        self.gemini_model = None

        if config.GEMINI_API_KEY:
            try:
                print("🧠 Configuring Google Gemini API...")
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel(config.GEMINI_MODEL)
                self.gemini_enabled = True
                print("✅ Google Gemini client ready!")
            except Exception as e:
                print(f"⚠️ Google Gemini configuration failed: {e}")

        # ── Groq (key-rotation pool) ───────────────────────────────
        self.groq_clients = []
        if any(key for key in config.GROQ_API_KEYS):
            try:
                self.groq_clients = [
                    Groq(api_key=key)
                    for key in config.GROQ_API_KEYS
                    if key
                ]
            except Exception as e:
                print(f"⚠️ Groq client initialization failed: {e}")
        self._groq_idx = 0

        self.groq_enabled = len(self.groq_clients) > 0

    # ────────────────────────────────────────────────────────────────
    #  Gemini Calls
    # ────────────────────────────────────────────────────────────────

    def call_gemini(self, prompt):
        """
        Call Gemini ``generate_content`` and return the text response.

        Raises RuntimeError with actionable instructions on 404 errors.
        """
        if not self.gemini_enabled:
            raise RuntimeError(
                "Google Gemini API is selected but GEMINI_API_KEY is not configured "
                "or client initialization failed. "
                "Please set the GEMINI_API_KEY environment variable. "
                "Note: Ensure your key is generated from Google AI Studio "
                "(https://aistudio.google.com/) or enable the "
                "'Generative Language API' in your GCP project."
            )

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = self.gemini_model.generate_content(prompt)
                return response.text.strip()
            except Exception as e:
                err_str = str(e)
                
                # Handle 429 Rate Limit (Free Tier)
                if "429" in err_str or "quota exceeded" in err_str.lower():
                    if attempt < max_attempts - 1:
                        match = re.search(r'retry in ([\d\.]+)s', err_str)
                        sleep_time = float(match.group(1)) + 1.0 if match else 60.0
                        print(f"⚠️ Gemini Rate Limit (429) hit. Sleeping for {sleep_time:.1f}s before retrying...", flush=True)
                        time.sleep(sleep_time)
                        continue
                    else:
                        raise RuntimeError(f"Gemini API rate limit exceeded after {max_attempts} attempts. Original error: {e}") from e

                # Handle 404 Model Not Found
                if "404" in err_str or "not found" in err_str.lower() or "ModelService" in err_str:
                    available_models = self._list_gemini_models()
                    raise RuntimeError(
                        "Gemini API model request failed with 404. This usually indicates "
                        "that the 'Generative Language API' is not enabled in your Google "
                        "Cloud Project. Please use an API key generated directly from "
                        "Google AI Studio (https://aistudio.google.com/) where this API "
                        "is enabled by default.\n"
                        f"Available models for this key: {available_models}. "
                        f"Original error: {e}"
                    ) from e
                
                # Re-raise other unexpected errors
                raise

    def _list_gemini_models(self):
        """Best-effort list of available generative models."""
        try:
            return [
                m.name for m in genai.list_models()
                if "generateContent" in m.supported_generation_methods
            ]
        except Exception as err:
            return [f"Failed to list models: {err}"]

    # ────────────────────────────────────────────────────────────────
    #  Groq Calls (with key rotation)
    # ────────────────────────────────────────────────────────────────

    def call_groq(self, **kwargs):
        """
        Call Groq ``chat.completions.create`` with automatic key rotation
        on 429 RateLimitErrors and exponential back-off.

        Accepts the same keyword arguments as the Groq SDK.
        """
        if not self.groq_clients:
            raise RuntimeError(
                "Groq API is selected but GROQ_API_KEY is not configured. "
                "Please set the GROQ_API_KEY environment variable."
            )

        max_attempts = len(self.groq_clients) * 3
        base_delay = 2.0

        for attempt in range(max_attempts):
            client = self.groq_clients[self._groq_idx]
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate_limit" in err_str or "limit reached" in err_str:
                    old_idx = self._groq_idx
                    self._groq_idx = (self._groq_idx + 1) % len(self.groq_clients)
                    print(
                        f"⚠️ Groq Rate Limit (429) hit on key index {old_idx}. "
                        f"Rotating to key index {self._groq_idx}...",
                        flush=True,
                    )
                    if self._groq_idx == 0:
                        cycle = attempt // len(self.groq_clients)
                        delay = base_delay * (2 ** cycle)
                        print(f"💤 All Groq keys rate-limited. Sleeping for {delay:.1f}s...", flush=True)
                        time.sleep(delay)
                    else:
                        time.sleep(0.5)
                else:
                    raise

        # Final fallback (no exception suppression)
        return self.groq_clients[self._groq_idx].chat.completions.create(**kwargs)

    # ────────────────────────────────────────────────────────────────
    #  Provider-Agnostic Dispatch
    # ────────────────────────────────────────────────────────────────

    def generate(self, prompt, *, provider=None, temperature=0.2):
        """
        Generate text using the specified or default LLM provider.

        Args:
            prompt: Plain text prompt (used directly for Gemini; wrapped
                    as a user message for Groq).
            provider: ``'gemini'`` or ``'groq'``.  Defaults to
                      ``config.LLM_PROVIDER``.
            temperature: Sampling temperature (Groq only).

        Returns:
            The generated text string.
        """
        provider = (provider or config.LLM_PROVIDER).strip().lower()

        if provider == "gemini":
            return self.call_gemini(prompt)

        if provider == "groq":
            response = self.call_groq(
                model=config.GROQ_MODEL,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip()

        raise ValueError(
            f"Invalid LLM provider: '{provider}'. Supported: 'gemini', 'groq'."
        )

    def chat(self, messages, *, provider=None, temperature=0.2):
        """
        Multi-turn chat generation.

        For Gemini, concatenates all messages into a single prompt.
        For Groq, passes the messages list natively.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            provider: ``'gemini'`` or ``'groq'``.
            temperature: Sampling temperature (Groq only).

        Returns:
            The generated text string.
        """
        provider = (provider or config.LLM_PROVIDER).strip().lower()

        if provider == "gemini":
            # Concatenate into a single prompt (Gemini doesn't use roles natively)
            parts = []
            for msg in messages:
                role_label = msg["role"].upper()
                parts.append(f"{role_label}: {msg['content']}")
            return self.call_gemini("\n\n".join(parts))

        if provider == "groq":
            response = self.call_groq(
                model=config.GROQ_MODEL,
                temperature=temperature,
                messages=messages,
            )
            return response.choices[0].message.content.strip()

        raise ValueError(
            f"Invalid LLM provider: '{provider}'. Supported: 'gemini', 'groq'."
        )

    def status_summary(self):
        """Return a human-readable status line for boot logging."""
        return (
            f"Default provider: {config.LLM_PROVIDER.upper()}, "
            f"Groq active: {self.groq_enabled}, "
            f"Gemini active: {self.gemini_enabled}"
        )
