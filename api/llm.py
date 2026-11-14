"""Provider-agnostic text generation for BurnBook.

Everything that calls a language model goes through `generate(system, prompt)`. Which model answers is set in the
environment, never in code, so a provider that breaks (retired model id, overload, quota) can be swapped or skipped
without touching the app.

Providers
    gemini     Google Gemini API.            Key: GEMINI_API_KEY or GOOGLE_API_KEY. Model: BURNBOOK_GEMINI_MODEL
    anthropic  Anthropic Messages API.       Key: ANTHROPIC_API_KEY. Model: BURNBOOK_ANTHROPIC_MODEL (or BURNBOOK_MODEL)
    openai     Any OpenAI-compatible API: OpenAI, Groq, OpenRouter, Together, Mistral, a local Ollama or LM Studio.
               Base URL: BURNBOOK_OPENAI_BASE_URL (default https://api.openai.com/v1)
               Key: BURNBOOK_OPENAI_API_KEY or OPENAI_API_KEY (may be empty for a local server)
               Model: BURNBOOK_OPENAI_MODEL (required; there is no default because names differ per service)

Order and fallback
    BURNBOOK_LLM=gemini,openai   try Gemini first, then the OpenAI-compatible service if Gemini fails
    BURNBOOK_LLM=none            turn written answers off
    unset                        every provider that is configured, in the order gemini, anthropic, openai
    (BURNBOOK_PROVIDER, the older single-provider switch, is still honoured and moves that provider to the front.)

Each provider retries rate-limit and overload errors (HTTP 429, 500, 502, 503, 504) a couple of times with a short
backoff, then the next provider in the list is tried. Keys are read from the environment only and are never logged
or returned by the API.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

TRANSIENT = {429, 500, 502, 503, 504}
DEFAULT_ORDER = ["gemini", "anthropic", "openai"]


class LLMUnavailable(RuntimeError):
    """No provider is configured, or every configured provider failed."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def _env(*names: str, default: str | None = None) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def describe_error(exc: Exception) -> str:
    """Short, key-safe description of a failed call (status code and provider message)."""
    if isinstance(exc, httpx.HTTPStatusError):
        msg = ""
        try:
            body = exc.response.json()
            err = body.get("error", body) if isinstance(body, dict) else {}
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            try:
                msg = exc.response.text[:200]
            except Exception:
                msg = ""
        return f"HTTP {exc.response.status_code}: {msg[:200]}".strip().rstrip(":")
    if isinstance(exc, LLMUnavailable):
        return str(exc)
    return f"{type(exc).__name__}: {str(exc)[:120]}".rstrip(": ")


class Provider:
    name = ""

    def configured(self) -> bool:
        raise NotImplementedError

    def model(self) -> str:
        raise NotImplementedError

    def _request(self, system: str, prompt: str, max_tokens: int, timeout: float) -> str:
        raise NotImplementedError

    def generate(self, system: str, prompt: str, max_tokens: int = 600, timeout: float = 30.0, retries: int = 2) -> str:
        for attempt in range(retries + 1):
            try:
                text = self._request(system, prompt, max_tokens, timeout).strip()
                if not text:
                    raise ValueError("empty response")
                return text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in TRANSIENT or attempt == retries:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("unreachable")  # pragma: no cover


class Gemini(Provider):
    name = "gemini"

    def configured(self):
        return bool(_env("GEMINI_API_KEY", "GOOGLE_API_KEY"))

    def model(self):
        return _env("BURNBOOK_GEMINI_MODEL", default="gemini-3.8-flash")

    def _request(self, system, prompt, max_tokens, timeout):
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model()}:generateContent",
            headers={"x-goog-api-key": _env("GEMINI_API_KEY", "GOOGLE_API_KEY"), "content-type": "application/json"},
            json={"system_instruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": max(max_tokens, 1024), "temperature": 0.2}},
            timeout=timeout,
        )
        r.raise_for_status()
        parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


class Anthropic(Provider):
    name = "anthropic"

    def configured(self):
        return bool(_env("ANTHROPIC_API_KEY"))

    def model(self):
        return _env("BURNBOOK_ANTHROPIC_MODEL", "BURNBOOK_MODEL", default="claude-sonnet-4-5")

    def _request(self, system, prompt, max_tokens, timeout):
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": _env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.model(), "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=timeout,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


class OpenAICompatible(Provider):
    name = "openai"

    def configured(self):
        return bool(_env("BURNBOOK_OPENAI_MODEL"))

    def model(self):
        return _env("BURNBOOK_OPENAI_MODEL", default="")

    def base_url(self):
        return _env("BURNBOOK_OPENAI_BASE_URL", default="https://api.openai.com/v1").rstrip("/")

    def _request(self, system, prompt, max_tokens, timeout):
        key = _env("BURNBOOK_OPENAI_API_KEY", "OPENAI_API_KEY")
        headers = {"content-type": "application/json"}
        if key:
            headers["authorization"] = f"Bearer {key}"
        r = httpx.post(
            f"{self.base_url()}/chat/completions",
            headers=headers,
            json={"model": self.model(), "max_tokens": max_tokens, "temperature": 0.2,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            timeout=timeout,
        )
        r.raise_for_status()
        choices = r.json().get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content") or ""


PROVIDERS: dict[str, Provider] = {p.name: p for p in (Gemini(), Anthropic(), OpenAICompatible())}


def order() -> list[str]:
    """Provider names to try, in order (configured ones only)."""
    raw = os.environ.get("BURNBOOK_LLM", "").strip().lower()
    if raw in ("none", "off", "0"):
        return []
    names = [n.strip() for n in raw.split(",") if n.strip()] if raw else list(DEFAULT_ORDER)
    names = ["openai" if n in ("openai_compat", "openai-compatible", "groq", "openrouter", "ollama") else n for n in names]
    forced = os.environ.get("BURNBOOK_PROVIDER", "").strip().lower()
    if forced in PROVIDERS and not raw:
        names = [forced] + [n for n in names if n != forced]
    seen, out = set(), []
    for n in names:
        if n in PROVIDERS and n not in seen and PROVIDERS[n].configured():
            seen.add(n)
            out.append(n)
    return out


def available() -> bool:
    return bool(order())


def generate(system: str, prompt: str, max_tokens: int = 600) -> LLMResult:
    """Try each configured provider in order; return the first answer or raise LLMUnavailable."""
    names = order()
    if not names:
        raise LLMUnavailable("no language model configured")
    errors = []
    for n in names:
        p = PROVIDERS[n]
        try:
            return LLMResult(p.generate(system, prompt, max_tokens), n, p.model())
        except Exception as exc:  # try the next provider
            errors.append(f"{n}: {describe_error(exc)}")
    raise LLMUnavailable("; ".join(errors), errors)


def status() -> dict:
    """What is configured, without exposing keys."""
    rows = []
    for n in DEFAULT_ORDER:
        p = PROVIDERS[n]
        row = {"provider": n, "configured": p.configured(), "model": p.model() or None}
        if n == "openai":
            row["base_url"] = p.base_url()
        rows.append(row)
    return {"order": order(), "providers": rows,
            "how_to_change": "Set BURNBOOK_LLM (e.g. 'gemini,openai') and each provider's key and model in the environment; see api/llm.py."}
