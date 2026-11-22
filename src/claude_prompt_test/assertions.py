"""Assertion checks. Each returns a list of failure messages (empty = pass)."""
from __future__ import annotations

import json
import re
from typing import Any

from .providers import Completion, Provider

JUDGE_TEMPLATE = """You are grading an AI model's output against a rubric.

Rubric:
{rubric}

Output to grade:
<output>
{output}
</output>

Reply with PASS or FAIL on the first line, then one short sentence of reasoning."""


def parse_json_output(text: str) -> Any:
    """Parse JSON, tolerating a surrounding ``` code fence."""
    s = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*?)\n?```$", s, re.DOTALL)
    if m:
        s = m.group(1)
    return json.loads(s)


def check_deterministic(output: str, a: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    for s in a.get("contains", []):
        if s not in output:
            fails.append(f"contains: {s!r} not found")
    for s in a.get("not_contains", []):
        if s in output:
            fails.append(f"not_contains: {s!r} found")
    for pat in a.get("regex", []):
        if not re.search(pat, output):
            fails.append(f"regex: /{pat}/ did not match")
    if "max_words" in a:
        n = len(output.split())
        if n > a["max_words"]:
            fails.append(f"max_words: {n} words > {a['max_words']}")
    if "starts_with" in a and not output.lstrip().startswith(a["starts_with"]):
        fails.append(f"starts_with: output does not start with {a['starts_with']!r}")
    if "equals" in a and output.strip() != a["equals"].strip():
        fails.append("equals: output differs from expected")
    if a.get("is_json") is True or "json_has_keys" in a:
        try:
            data = parse_json_output(output)
        except (ValueError, TypeError):
            fails.append("is_json: output is not valid JSON")
        else:
            keys = a.get("json_has_keys", [])
            if keys:
                if not isinstance(data, dict):
                    fails.append("json_has_keys: JSON is not an object")
                else:
                    for k in keys:
                        if k not in data:
                            fails.append(f"json_has_keys: key {k!r} missing")
    return fails


def run_judge(provider: Provider, model: str, rubric: str, output: str,
              max_tokens: int = 512) -> tuple[bool, str, Completion]:
    prompt = JUDGE_TEMPLATE.format(rubric=rubric, output=output)
    c = provider.complete(model=model, system=None, prompt=prompt,
                          max_tokens=max_tokens, purpose="judge")
    lines = c.text.strip().splitlines()
    verdict = lines[0].strip().upper() if lines else ""
    reason = " ".join(l.strip() for l in lines[1:])[:200]
    if verdict.startswith("PASS"):
        return True, reason, c
    if verdict.startswith("FAIL"):
        return False, reason, c
    return False, f"unparseable judge verdict: {c.text.strip()[:80]!r}", c
