"""
qwen-track3/qwen_client.py
===========================
Qwen Cloud client for the CORVUS-CRONOS negotiation engine.

Uses the DashScope international endpoint with HTTP directly (no openai SDK).
Pattern follows raven-memory/raven/qwen_client.py and rebound/src/memory/agent.py.

Set DASHSCOPE_API_KEY to enable Qwen Cloud.
Without it the system runs fully deterministically (offline fallback).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import requests

log = logging.getLogger("qwen_track3.client")

# ---------------------------------------------------------------------------
# Constants — Qwen Cloud (DashScope international endpoint)
# ---------------------------------------------------------------------------

QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
QWEN_DEFAULT_MODEL = "qwen-plus"

_API_RETRIES = 2          # total attempts = 1 + _API_RETRIES
_API_BACKOFF_BASE = 0.5   # seconds, exponential

# ---------------------------------------------------------------------------
# System prompt for the negotiation narrator
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a forensic communication analyst. You narrate multi-agent negotiation
results produced by CORVUS — a deterministic rhetorical analysis engine.

Your role is STRICTLY NARRATIVE: you explain what happened in the negotiation.
You CANNOT change the verdict, score, or any numeric value. All of those are
sealed before you are called and are shown below.

Six specialized agents analyzed the text simultaneously:
  L1 (Grice)      — cooperative principle maxim violations
  L2 (Carnegie)   — influence tactics and Cialdini principles
  L3 (Aristotle)  — ethos / pathos / logos rhetorical imbalance
  L4 (Berne)      — transactional ego states and ulterior agendas
  L5 (Linguistics)— cognitive load, register anomaly, Zipf imperfection
  L6 (Peirce)     — abductive synthesis over L1-L5 (Firstness/Secondness/Thirdness)

A corroboration gate required >= 2 agents to fire for any verdict above SILENT.
CRONOS recorded every vote as a SHA-256 linked hypothesis trace — tamper-evident.

Be precise, professional, and grounded. Do not invent evidence.
"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class QwenClient:
    """
    Thin synchronous HTTP wrapper for the Qwen Cloud Chat Completions API.

    Uses requests directly — no openai SDK dependency.
    Implements exponential backoff retry (same pattern as raven-memory).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = QWEN_DEFAULT_MODEL,
        base_url: str = QWEN_BASE_URL,
        timeout: int = 30,
        max_tokens: int = 600,
        temperature: float = 0.3,
    ) -> None:
        self.api_key    = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.model      = model
        self.base_url   = base_url.rstrip("/")
        self.timeout    = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._session   = requests.Session()

    @property
    def available(self) -> bool:
        """True when an API key is configured."""
        return bool(self.api_key)

    def complete(self, user_message: str, system_prompt: str = _SYSTEM_PROMPT) -> str:
        """
        Single chat completion call with retry.

        Returns the model content string, or an offline-mode placeholder
        if no API key is set or all retries fail.
        """
        if not self.api_key:
            return self._offline(user_message)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
        }

        last_err: Optional[Exception] = None
        for attempt in range(1 + _API_RETRIES):
            try:
                resp = self._session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:
                last_err = exc
                if attempt < _API_RETRIES:
                    delay = _API_BACKOFF_BASE * (2 ** attempt)
                    log.warning(
                        "Qwen API attempt %d/%d failed (%s) — retrying in %.1fs",
                        attempt + 1, 1 + _API_RETRIES, exc, delay,
                    )
                    time.sleep(delay)

        log.error("Qwen API failed after %d attempts: %s", 1 + _API_RETRIES, last_err)
        # A key IS configured here — telling the user to set DASHSCOPE_API_KEY
        # (the offline message) would be misleading. Surface the actual failure.
        return (
            f"[QWEN NARRATION UNAVAILABLE — API call failed after "
            f"{1 + _API_RETRIES} attempts: {last_err}]\n\n"
            f"Query: {user_message[:200]}"
        )

    @staticmethod
    def _offline(user_message: str) -> str:
        return (
            "[OFFLINE — set DASHSCOPE_API_KEY for Qwen narration]\n\n"
            f"Query: {user_message[:200]}"
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "QwenClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
