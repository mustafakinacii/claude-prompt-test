# claude-prompt-test

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![status](https://img.shields.io/badge/status-early%20(v0.1)-orange)
![deps](https://img.shields.io/badge/deps-anthropic%20%2B%20pyyaml-lightgrey)

Unit tests for your prompts. Write test cases in YAML, run them against Claude, fail your CI when a prompt stops doing its job.

> Independent open-source project. Not affiliated with, endorsed by, or sponsored by Anthropic.

> **Verification status:** the test suite and all example output below use the built-in fake provider (`--dry-run`). The real Anthropic provider is written against the installed `anthropic` SDK (2.12.0) signatures, but it has **not been run against the live API yet**, because no API key was available when this was built. See [Limitations](#limitations).

## The problem

Prompts break silently. You tweak a sentence, upgrade the model, or change the input format, and nothing crashes: the output is just a little worse, or the JSON is missing a key, or the answer got three times longer. You find out from users. `claude-prompt-test` lets you pin down the behavior you care about as cheap, repeatable checks, like unit tests for code.

## Install

```bash
git clone https://github.com/mustafakinacii/claude-prompt-test
cd claude-prompt-test
python3 -m venv .venv && source .venv/bin/activate
pip install .
export ANTHROPIC_API_KEY=...   # read from the environment only
```

Requires Python 3.10+. Dependencies: `anthropic`, `pyyaml`.

## Quick start

```bash
claude-prompt-test init                      # writes a sample prompts.yaml
claude-prompt-test run prompts.yaml --dry-run   # no API call, no key needed
claude-prompt-test run prompts.yaml          # real run (needs ANTHROPIC_API_KEY)
```

`prompts.yaml`:

```yaml
model: claude-haiku-5-5        # default if omitted
max_tokens: 4096
system: You are a concise support assistant.   # optional
prompt: |
  Summarize this customer message in one sentence and name the sentiment.
  Message: {{message}}
tests:
  - name: angry customer
    vars:
      message: "My order arrived broken and nobody answers my emails."
    assert:
      regex: "(?i)negative"
      max_words: 60
      not_contains: "As an AI"
```

Variables use `{{name}}` and may appear in `prompt` and `system`. Every variable must be defined in each test's `vars`, and every test needs at least one assertion; otherwise the file is rejected before anything is sent.

### Dry-run output (fake provider, not a real model)

The dry-run provider echoes the prompt back as the "answer" and counts words as tokens. It exists to check your YAML and wiring, so assertions here say nothing about real model behavior. This is real output from `examples/failing.yaml`, a file written to fail:

```text
$ claude-prompt-test run examples/failing.yaml --dry-run --repeat 2 --price-in 1 --price-out 5
DRY RUN: FakeProvider, no model was called. Token counts are word counts.
model: claude-haiku-5-5   runs: 6   repeat: 2

STATUS  CASE         LATENCY  IN TOK  OUT TOK  DETAILS
FAIL    too long #1  0.00s    5       6        max_words: 6 words > 2
FAIL    too long #2  0.00s    5       6        max_words: 6 words > 2
FAIL    is json #1   0.00s    5       6        is_json: output is not valid JSON
FAIL    is json #2   0.00s    5       6        is_json: output is not valid JSON
PASS    ok #1        0.00s    5       6
PASS    ok #2        0.00s    5       6

2/6 passed, 4 failed
tokens: 30 in, 36 out
Estimated cost: 0.000210 (tokens x the prices you passed: in=1.0/M, out=5.0/M; your currency, not verified)
exit=1
```

(`exit=1` is the process exit code, shown for illustration. The prices `1` and `5` are placeholder numbers typed on the command line, not real prices.)

## Assertions

Put any combination under a test's `assert:`. All must pass.

| Key | Value | Passes when |
|---|---|---|
| `contains` | string or list | every string appears in the output |
| `not_contains` | string or list | none of the strings appear |
| `regex` | string or list | every pattern matches somewhere (`re.search`) |
| `max_words` | integer | output has at most N whitespace-separated words |
| `is_json` | `true` | output parses as JSON (a surrounding ```` ``` ```` fence is tolerated) |
| `json_has_keys` | string or list | output is a JSON object containing all keys (implies `is_json`) |
| `starts_with` | string | output, ignoring leading whitespace, starts with it |
| `equals` | string | output equals it, ignoring surrounding whitespace |
| `llm_judge` | rubric string | a second Claude call answers PASS for the rubric. **Off by default**; enable with `--judge`. Uses `judge_model` from the file, else the main model |

## CLI

```
claude-prompt-test run FILE [--model M] [--repeat N] [--concurrency N]
                            [--judge] [--json] [--dry-run]
                            [--price-in P] [--price-out P]
claude-prompt-test init [PATH] [--force]
```

- **Exit codes:** `0` all passed, `1` at least one case failed or errored, `2` usage/YAML/config error (including a missing `ANTHROPIC_API_KEY`).
- **`--repeat N`** runs every case N times and reports cases that both passed and failed as `FLAKY`. Useful because model output is not deterministic.
- **`--concurrency N`** runs requests in parallel threads.
- **`--json`** prints a machine-readable report (summary plus per-run results including the raw output).
- **Cost:** an `Estimated cost` line appears only if you pass both `--price-in` and `--price-out` (price per million tokens). No prices are built in; look up current ones yourself.
- **Judge calls** add their tokens and latency to that case's numbers.

## CI example (GitHub Actions)

```yaml
name: prompt-tests
on: [pull_request]
jobs:
  prompts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install git+https://github.com/mustafakinacii/claude-prompt-test
      - run: claude-prompt-test run prompts.yaml --repeat 3 --concurrency 4
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Real calls cost money; keep `--repeat` and the number of cases modest on every PR.

## Design

`Provider` is a small interface (`complete(model, system, prompt, max_tokens, purpose) -> Completion`). `AnthropicProvider` wraps `anthropic.Anthropic().messages.create`; `FakeProvider` is deterministic and offline, and is what the tests and `--dry-run` use.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Test status at the time of writing: 58 tests pass, all with `FakeProvider`.

## Limitations

- **Live API path is unverified.** No API key was available during development, so `AnthropicProvider` has never made a real request. It follows the documented SDK 2.12.0 `messages.create` signature, but treat v0.1 as untested against the live service until you run it once yourself and report problems.
- The default model id `claude-haiku-5-5` is taken from the author's instructions and was not checked against the live models list. Set `model:` or `--model` to whatever you use.
- `max_tokens` defaults to 4096. Models that think before answering may spend part of it on thinking; raise it if outputs get cut off.
- Only plain text output is checked; no tool use, images, multi-turn conversations, or streaming.
- `llm_judge` is itself a model output: it can be wrong or flaky. Prefer deterministic assertions where you can.
- Token counts come from the API's usage field in real runs; in `--dry-run` they are word counts.
- Retries and rate-limit handling are whatever the SDK does by default.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Mustafa Kınacı.
