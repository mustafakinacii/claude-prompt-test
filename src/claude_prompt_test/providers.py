"""Provider interface, the real Anthropic provider, and a fake for tests/dry runs."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Protocol


class ProviderError(Exception):
    """A provider call failed (network, auth, API error)."""


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class Provider(Protocol):
    def complete(self, *, model: str, system: str | None, prompt: str,
                 max_tokens: int, purpose: str = "test") -> Completion:
        """Run one completion. `purpose` is "test" or "judge"."""
        ...


class AnthropicProvider:
    """Real provider. Reads ANTHROPIC_API_KEY from the environment only."""

    def __init__(self) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set (use --dry-run to run without a key)")
        import anthropic  # imported lazily so tests/dry runs never need it configured

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key)

    def complete(self, *, model, system, prompt, max_tokens, purpose="test") -> Completion:
        kwargs = {"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        start = time.perf_counter()
        try:
            msg = self._client.messages.create(**kwargs)
        except self._anthropic.APIError as e:
            raise ProviderError(f"{type(e).__name__}: {e}") from e
        latency = time.perf_counter() - start
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return Completion(text=text, input_tokens=msg.usage.input_tokens,
                          output_tokens=msg.usage.output_tokens, latency_s=latency)


class FakeProvider:
    """Deterministic provider for tests and `--dry-run`. Never touches the network.

    `responder(system, prompt, purpose)` returns the text. The default echoes the
    prompt (and answers "PASS" to judge calls), so dry runs exercise everything
    except the model itself. Token counts are word counts, not real usage.
    """

    def __init__(self, responder: Callable[[str | None, str, str], str] | None = None) -> None:
        self.responder = responder or self._default
        self.calls: list[dict] = []

    @staticmethod
    def _default(system, prompt, purpose):
        if purpose == "judge":
            return "PASS\ndry-run judge: no model was consulted."
        return "[dry-run] " + prompt

    def complete(self, *, model, system, prompt, max_tokens, purpose="test") -> Completion:
        self.calls.append({"model": model, "system": system, "prompt": prompt, "purpose": purpose})
        start = time.perf_counter()
        out = self.responder(system, prompt, purpose)
        if isinstance(out, Exception):
            raise out
        return Completion(text=out, input_tokens=len(prompt.split()),
                          output_tokens=len(out.split()),
                          latency_s=time.perf_counter() - start)
