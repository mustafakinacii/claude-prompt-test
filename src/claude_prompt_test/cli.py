"""Command line interface."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .providers import AnthropicProvider, FakeProvider, ProviderError
from .runner import RunResult, run_all, summarize
from .spec import DEFAULT_MODEL, SpecError, load_spec

SAMPLE = '''\
# prompts.yaml - run with: claude-prompt-test run prompts.yaml
model: claude-haiku-5-5
max_tokens: 4096
system: You are a concise support assistant. Answer in plain text.
prompt: |
  Summarize this customer message in one sentence and name the sentiment
  (positive, neutral or negative).

  Message: {{message}}

tests:
  - name: angry customer
    vars:
      message: "My order arrived broken and nobody answers my emails."
    assert:
      regex: "(?i)negative"
      max_words: 60
      not_contains: "As an AI"

  - name: happy customer
    vars:
      message: "Delivery was fast and the product is great, thanks!"
    assert:
      regex: "(?i)positive"
      # llm_judge needs --judge (makes a second Claude call per case)
      llm_judge: "The summary is a single sentence and matches the message."
'''


def _fmt_cost(s: dict, price_in: float | None, price_out: float | None) -> str | None:
    if price_in is None or price_out is None:
        return None
    cost = s["input_tokens"] / 1e6 * price_in + s["output_tokens"] / 1e6 * price_out
    return (f"Estimated cost: {cost:.6f} (tokens x the prices you passed: "
            f"in={price_in}/M, out={price_out}/M; your currency, not verified)")


def render_table(results: list[RunResult], repeat: int) -> str:
    rows = [("STATUS", "CASE", "LATENCY", "IN TOK", "OUT TOK", "DETAILS")]
    for r in results:
        name = r.case if repeat == 1 else f"{r.case} #{r.run}"
        status = "PASS" if r.passed else ("ERROR" if r.error else "FAIL")
        detail = r.error or "; ".join(r.failures)
        rows.append((status, name, f"{r.latency_s:.2f}s", str(r.input_tokens),
                     str(r.output_tokens), detail))
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    lines = []
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(5)) + "  " + row[5])
    return "\n".join(l.rstrip() for l in lines)


def cmd_init(args) -> int:
    if os.path.exists(args.path) and not args.force:
        print(f"error: {args.path} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    with open(args.path, "w", encoding="utf-8") as f:
        f.write(SAMPLE)
    print(f"wrote {args.path}")
    return 0


def cmd_run(args, provider=None) -> int:
    try:
        spec = load_spec(args.file)
    except SpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.model:
        spec.model = args.model
    if args.repeat < 1 or args.concurrency < 1:
        print("error: --repeat and --concurrency must be >= 1", file=sys.stderr)
        return 2
    if provider is None:
        if args.dry_run:
            provider = FakeProvider()
        else:
            try:
                provider = AnthropicProvider()
            except ProviderError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2

    results = run_all(spec, provider, repeat=args.repeat, concurrency=args.concurrency,
                      use_judge=args.judge)
    s = summarize(results)
    skipped_judge = 0 if args.judge else sum(
        1 for c in spec.tests if "llm_judge" in c.assertions)
    cost = _fmt_cost(s, args.price_in, args.price_out)

    if args.json:
        print(json.dumps({
            "model": spec.model, "dry_run": bool(args.dry_run), "repeat": args.repeat,
            "summary": {**s, "estimated_cost": None if cost is None else
                        s["input_tokens"] / 1e6 * args.price_in
                        + s["output_tokens"] / 1e6 * args.price_out},
            "results": [r.__dict__ for r in results],
        }, indent=2, ensure_ascii=False))
    else:
        if args.dry_run:
            print("DRY RUN: FakeProvider, no model was called. Token counts are word counts.")
        print(f"model: {spec.model}   runs: {s['runs']}   repeat: {args.repeat}\n")
        print(render_table(results, args.repeat))
        print(f"\n{s['passed']}/{s['runs']} passed, {s['failed']} failed")
        if s["flaky"]:
            print("FLAKY (passed and failed across repeats): " + ", ".join(s["flaky"]))
        if skipped_judge:
            print(f"note: llm_judge skipped for {skipped_judge} case(s); pass --judge to enable")
        print(f"tokens: {s['input_tokens']} in, {s['output_tokens']} out")
        if cost:
            print(cost)
    return 1 if s["failed"] else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-prompt-test",
        description="Unit tests for prompts. Independent project, not affiliated with Anthropic.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the tests in a prompts.yaml")
    r.add_argument("file")
    r.add_argument("--model", help=f"override the model from the file (default {DEFAULT_MODEL})")
    r.add_argument("--repeat", type=int, default=1, help="run each case N times to catch flaky prompts")
    r.add_argument("--concurrency", type=int, default=1, help="parallel requests")
    r.add_argument("--judge", action="store_true", help="enable llm_judge assertions (extra Claude call)")
    r.add_argument("--json", action="store_true", help="print JSON instead of a table")
    r.add_argument("--dry-run", action="store_true", help="use the fake provider; no API call, no key needed")
    r.add_argument("--price-in", type=float, help="price per million input tokens (you supply it)")
    r.add_argument("--price-out", type=float, help="price per million output tokens (you supply it)")
    r.set_defaults(func=cmd_run)

    i = sub.add_parser("init", help="write a sample prompts.yaml")
    i.add_argument("path", nargs="?", default="prompts.yaml")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)
    return p


def main(argv=None, provider=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args, provider)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
