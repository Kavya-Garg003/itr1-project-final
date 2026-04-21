"""
shared/llm_client.py — Unified LLM Client with Automatic Fallback
===================================================================
Tries providers in order until one succeeds. Groq and OpenRouter both
use the OpenAI-compatible API format, so the same `openai` package
works for all three — no extra dependencies.

Provider priority (best free first):
  1. Groq       — llama-3.3-70b-versatile (free tier: 14,400 req/day, 500K tokens/day)
  2. OpenRouter  — meta-llama/llama-3.3-70b-instruct:free (free, no rate limit listed)
  3. Groq fast  — llama-3.1-8b-instant (faster fallback when 70B rate-limited)
  4. OpenAI     — gpt-4o-mini (paid, absolute last resort)

To use:
    from shared.llm_client import complete, complete_with_system

    answer = complete("What is the 80C deduction limit?")
    answer = complete_with_system(
        system="You are a tax assistant...",
        user="What is the HRA exemption formula?"
    )

Environment variables needed in .env:
    GROQ_API_KEY=gsk_...        ← get free at console.groq.com
    OPENROUTER_API_KEY=sk-or-.. ← get free at openrouter.ai
    OPENAI_API_KEY=sk-...       ← optional, paid fallback only
"""

from __future__ import annotations
import os
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ── Provider config ────────────────────────────────────────────────────────────

PROVIDERS = [
    {
        "name":     "groq-70b",
        "label":    "Groq llama-3.3-70b",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key":  lambda: os.getenv("GROQ_API_KEY", ""),
        "model":    "llama-3.3-70b-versatile",
        "max_tokens": 1024,
    },
    {
        "name":     "openrouter-llama",
        "label":    "OpenRouter llama-3.3-70b (free)",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key":  lambda: os.getenv("OPENROUTER_API_KEY", ""),
        "model":    "meta-llama/llama-3.3-70b-instruct:free",
        "max_tokens": 1024,
        "extra_headers": {
            "HTTP-Referer": "https://itr1-rag-agent.local",
            "X-Title":      "ITR-1 RAG Agent",
        },
    },
    {
        "name":     "openrouter-deepseek",
        "label":    "OpenRouter DeepSeek (free)",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key":  lambda: os.getenv("OPENROUTER_API_KEY", ""),
        "model":    "deepseek/deepseek-chat:free",
        "max_tokens": 1024,
        "extra_headers": {
            "HTTP-Referer": "https://itr1-rag-agent.local",
            "X-Title":      "ITR-1 RAG Agent",
        },
    },
    {
        "name":     "groq-8b",
        "label":    "Groq llama-3.1-8b (fast fallback)",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key":  lambda: os.getenv("GROQ_API_KEY", ""),
        "model":    "llama-3.1-8b-instant",
        "max_tokens": 1024,
    },
    {
        "name":     "openai",
        "label":    "OpenAI gpt-4o-mini (paid last resort)",
        "base_url": None,                               # use default OpenAI endpoint
        "api_key":  lambda: os.getenv("OPENAI_API_KEY", ""),
        "model":    "gpt-4o-mini",
        "max_tokens": 1024,
    },
]

# Errors that mean "try next provider" vs "something else is wrong"
_SKIP_ERRORS = (
    "rate_limit_exceeded",
    "rate limit",
    "quota",
    "model_not_found",
    "model not found",
    "insufficient_quota",
    "context_length_exceeded",   # try smaller model
    "overloaded",
    "service unavailable",
    "503",
    "529",
)


def _should_skip(err_str: str) -> bool:
    return any(s in err_str.lower() for s in _SKIP_ERRORS)


def _call_provider(provider: dict, messages: list[dict], temperature: float) -> str:
    """Call one provider. Returns text or raises."""
    from openai import OpenAI

    api_key = provider["api_key"]()
    if not api_key:
        raise ValueError(f"No API key set for {provider['name']}")

    kwargs = dict(
        api_key=api_key,
        max_retries=0,
    )
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]

    client = OpenAI(**kwargs)

    extra_headers = provider.get("extra_headers", {})

    resp = client.chat.completions.create(
        model=provider["model"],
        messages=messages,
        temperature=temperature,
        max_tokens=provider["max_tokens"],
        extra_headers=extra_headers if extra_headers else None,
    )
    return resp.choices[0].message.content.strip()


# ── Public API ─────────────────────────────────────────────────────────────────

def complete(
    prompt:      str,
    system:      Optional[str] = None,
    temperature: float         = 0.0,
    providers:   Optional[list[dict]] = None,
) -> str:
    """
    Send a completion request, trying providers in order until one succeeds.

    Args:
        prompt:      The user message / question.
        system:      Optional system prompt.
        temperature: 0.0 for deterministic (tax answers), 0.3 for more variety.
        providers:   Override the default provider list (for testing).

    Returns:
        The model's response as a string.

    Raises:
        RuntimeError: If all providers fail.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    return _try_providers(messages, temperature, providers or PROVIDERS)


def complete_with_system(
    system:      str,
    user:        str,
    temperature: float = 0.0,
    providers:   Optional[list[dict]] = None,
) -> str:
    """Convenience wrapper — common pattern in the codebase."""
    return complete(user, system=system, temperature=temperature, providers=providers)


def complete_vision(
    prompt:             str,
    base64_images:      list[str],
    system:             Optional[str] = None,
    temperature:        float         = 0.0,
    providers:          Optional[list[dict]] = None,
) -> str:
    """Send an image-capable completion request to Vision-supported providers."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    
    content = []
    for b64 in base64_images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    content.append({"type": "text", "text": prompt})
    
    messages.append({"role": "user", "content": content})

    vision_providers = [
        {
            "name":     "openrouter-llama-vision",
            "label":    "OpenRouter Llama-3.2 90B Vision (free)",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key":  lambda: os.getenv("OPENROUTER_API_KEY", ""),
            "model":    "meta-llama/llama-3.2-90b-vision-instruct:free",
            "max_tokens": 2048,
            "extra_headers": {
                "HTTP-Referer": "https://itr1-rag-agent.local",
                "X-Title":      "ITR-1 RAG Agent",
            },
        },
        {
            "name":     "groq-11b-vision",
            "label":    "Groq Llama-3.2 11B Vision",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key":  lambda: os.getenv("GROQ_API_KEY", ""),
            "model":    "llama-3.2-11b-vision-preview",
            "max_tokens": 2048,
        },
        {
            "name":     "groq-90b-vision",
            "label":    "Groq Llama-3.2 90B Vision",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key":  lambda: os.getenv("GROQ_API_KEY", ""),
            "model":    "llama-3.2-90b-vision-preview",
            "max_tokens": 2048,
        }
    ]

    return _try_providers(messages, temperature, providers or vision_providers)


def _try_providers(
    messages:    list[dict],
    temperature: float,
    provider_list: list[dict],
) -> str:
    errors = []

    for provider in provider_list:
        api_key = provider["api_key"]()
        if not api_key:
            log.debug("Skipping %s — no API key set", provider["name"])
            continue

        try:
            log.info("Trying %s...", provider["label"])
            result = _call_provider(provider, messages, temperature)
            log.info("Success with %s", provider["label"])
            return result

        except Exception as e:
            err_str = str(e)
            errors.append(f"{provider['label']}: {err_str[:120]}")
            log.warning("Provider %s failed: %s", provider["name"], err_str[:120])

            if _should_skip(err_str):
                # Rate limit / quota → try next immediately
                continue
            else:
                # Unknown error → brief pause then try next
                time.sleep(0.5)
                continue

    raise RuntimeError(
        "All LLM providers failed. Errors:\n" +
        "\n".join(f"  • {e}" for e in errors) +
        "\n\nCheck that at least GROQ_API_KEY or OPENROUTER_API_KEY is set in .env"
    )


# ── LangChain-compatible shim (used by itr_graph.py) ──────────────────────────

class FallbackLLM:
    """
    Thin wrapper that looks like a LangChain ChatModel to existing calling code.
    Replaces ChatOpenAI — same .invoke(messages) interface, uses fallback internally.
    """

    def __init__(self, temperature: float = 0.0, provider_list: Optional[list] = None):
        self.temperature   = temperature
        self.provider_list = provider_list or PROVIDERS

    def invoke(self, messages) -> "_FakeResponse":
        # Accept both LangChain message objects and plain dicts
        plain_messages = []
        for m in messages:
            if hasattr(m, "type") and hasattr(m, "content"):
                # LangChain message object
                role = "system" if "system" in m.type else "user"
                plain_messages.append({"role": role, "content": m.content})
            elif isinstance(m, dict):
                plain_messages.append(m)
            else:
                plain_messages.append({"role": "user", "content": str(m)})

        text = _try_providers(plain_messages, self.temperature, self.provider_list)
        return _FakeResponse(text)


class _FakeResponse:
    """Mimics langchain_core message response object."""
    def __init__(self, content: str):
        self.content = content

    def __str__(self):
        return self.content


def get_llm(temperature: float = 0.0) -> FallbackLLM:
    """
    Drop-in replacement for _get_llm() in itr_graph.py.
    Returns a FallbackLLM that behaves like ChatOpenAI.
    """
    return FallbackLLM(temperature=temperature)


# ── Quick test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("Testing LLM fallback chain...")
    print("Available providers:")
    for p in PROVIDERS:
        key = p["api_key"]()
        status = "✓ key set" if key else "✗ no key"
        print(f"  {p['label']:45} {status}")

    print("\nSending test prompt...")
    try:
        ans = complete(
            prompt="In one sentence, what is the Section 80C deduction limit for AY 2024-25?",
            system="You are a concise Indian income tax assistant.",
        )
        print(f"\nAnswer: {ans}")
    except RuntimeError as e:
        print(f"\nAll providers failed:\n{e}")
        sys.exit(1)
