"""Loading and validating prompts.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_MAX_TOKENS = 4096

ASSERTION_KEYS = {
    "contains", "not_contains", "regex", "max_words", "is_json",
    "json_has_keys", "starts_with", "equals", "llm_judge",
}
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class SpecError(Exception):
    """Raised when prompts.yaml is missing, malformed or inconsistent."""


@dataclass
class TestCase:
    name: str
    vars: dict[str, str]
    assertions: dict[str, Any]


@dataclass
class Spec:
    prompt: str
    system: str | None
    model: str
    max_tokens: int
    judge_model: str | None
    tests: list[TestCase] = field(default_factory=list)


def template_vars(template: str) -> set[str]:
    return set(_VAR_RE.findall(template))


def render(template: str, variables: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            raise SpecError(f"missing variable '{key}'")
        return variables[key]

    return _VAR_RE.sub(sub, template)


def _as_list(value: Any, key: str, where: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return [value]
    raise SpecError(f"{where}: '{key}' must be a string or a list")


def _validate_assertions(raw: Any, where: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SpecError(f"{where}: 'assert' must be a mapping")
    unknown = set(raw) - ASSERTION_KEYS
    if unknown:
        raise SpecError(
            f"{where}: unknown assertion(s) {sorted(unknown)}; "
            f"valid: {sorted(ASSERTION_KEYS)}"
        )
    out: dict[str, Any] = dict(raw)
    for key in ("contains", "not_contains", "regex"):
        if key in out:
            out[key] = [str(v) for v in _as_list(out[key], key, where)]
    if "regex" in out:
        for pat in out["regex"]:
            try:
                re.compile(pat)
            except re.error as e:
                raise SpecError(f"{where}: invalid regex {pat!r}: {e}") from e
    if "max_words" in out:
        v = out["max_words"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise SpecError(f"{where}: 'max_words' must be a non-negative integer")
    if "is_json" in out and not isinstance(out["is_json"], bool):
        raise SpecError(f"{where}: 'is_json' must be true or false")
    if "json_has_keys" in out:
        out["json_has_keys"] = [str(v) for v in _as_list(out["json_has_keys"], "json_has_keys", where)]
    for key in ("starts_with", "equals", "llm_judge"):
        if key in out and not isinstance(out[key], str):
            raise SpecError(f"{where}: '{key}' must be a string")
    return out


def parse_spec(text: str) -> Spec:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecError(f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SpecError("top level of the file must be a mapping")

    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SpecError("'prompt' is required and must be a non-empty string")
    system = data.get("system")
    if system is not None and not isinstance(system, str):
        raise SpecError("'system' must be a string")
    model = data.get("model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model:
        raise SpecError("'model' must be a string")
    max_tokens = data.get("max_tokens", DEFAULT_MAX_TOKENS)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise SpecError("'max_tokens' must be a positive integer")
    judge_model = data.get("judge_model")
    if judge_model is not None and not isinstance(judge_model, str):
        raise SpecError("'judge_model' must be a string")

    raw_tests = data.get("tests")
    if not isinstance(raw_tests, list) or not raw_tests:
        raise SpecError("'tests' is required and must be a non-empty list")

    needed = template_vars(prompt) | (template_vars(system) if system else set())
    tests: list[TestCase] = []
    seen: set[str] = set()
    for i, t in enumerate(raw_tests, 1):
        if not isinstance(t, dict):
            raise SpecError(f"tests[{i}] must be a mapping")
        name = str(t.get("name", f"case {i}"))
        where = f"test '{name}'"
        if name in seen:
            raise SpecError(f"duplicate test name '{name}'")
        seen.add(name)
        raw_vars = t.get("vars") or {}
        if not isinstance(raw_vars, dict):
            raise SpecError(f"{where}: 'vars' must be a mapping")
        variables = {str(k): str(v) for k, v in raw_vars.items()}
        missing = needed - set(variables)
        if missing:
            raise SpecError(f"{where}: missing variable(s) {sorted(missing)}")
        assertions = _validate_assertions(t.get("assert"), where)
        if not assertions:
            raise SpecError(f"{where}: needs at least one assertion under 'assert'")
        tests.append(TestCase(name=name, vars=variables, assertions=assertions))

    return Spec(prompt=prompt, system=system, model=model, max_tokens=max_tokens,
                judge_model=judge_model, tests=tests)


def load_spec(path: str) -> Spec:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise SpecError(f"cannot read {path}: {e.strerror or e}") from e
    return parse_spec(text)
