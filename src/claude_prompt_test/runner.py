"""Run test cases (optionally repeated, concurrently) and collect results."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .assertions import check_deterministic, run_judge
from .providers import Provider, ProviderError
from .spec import Spec, TestCase, render


@dataclass
class RunResult:
    case: str
    run: int
    passed: bool
    failures: list[str] = field(default_factory=list)
    error: str | None = None
    output: str = ""
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


def run_one(spec: Spec, case: TestCase, run: int, provider: Provider,
            use_judge: bool) -> RunResult:
    res = RunResult(case=case.name, run=run, passed=False)
    try:
        system = render(spec.system, case.vars) if spec.system else None
        prompt = render(spec.prompt, case.vars)
        c = provider.complete(model=spec.model, system=system, prompt=prompt,
                              max_tokens=spec.max_tokens, purpose="test")
        res.output = c.text
        res.latency_s = c.latency_s
        res.input_tokens = c.input_tokens
        res.output_tokens = c.output_tokens
        res.failures = check_deterministic(c.text, case.assertions)
        rubric = case.assertions.get("llm_judge")
        if rubric and use_judge:
            ok, reason, jc = run_judge(provider, spec.judge_model or spec.model, rubric, c.text)
            res.input_tokens += jc.input_tokens
            res.output_tokens += jc.output_tokens
            res.latency_s += jc.latency_s
            if not ok:
                res.failures.append(f"llm_judge: {reason}")
        elif rubric:
            pass  # judge is off by default; reported as skipped by the CLI
        res.passed = not res.failures
    except ProviderError as e:
        res.error = str(e)
    except Exception as e:  # spec/render errors surface as a failed case, not a crash
        res.error = f"{type(e).__name__}: {e}"
    return res


def run_all(spec: Spec, provider: Provider, *, repeat: int = 1, concurrency: int = 1,
            use_judge: bool = False) -> list[RunResult]:
    jobs = [(c, r) for c in spec.tests for r in range(1, repeat + 1)]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = [ex.submit(run_one, spec, c, r, provider, use_judge) for c, r in jobs]
        return [f.result() for f in futures]  # preserves job order


def summarize(results: list[RunResult]) -> dict:
    by_case: dict[str, list[RunResult]] = {}
    for r in results:
        by_case.setdefault(r.case, []).append(r)
    flaky = [n for n, rs in by_case.items()
             if len(rs) > 1 and 0 < sum(x.passed for x in rs) < len(rs)]
    return {
        "runs": len(results),
        "passed": sum(r.passed for r in results),
        "failed": sum(not r.passed for r in results),
        "flaky": flaky,
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
    }
