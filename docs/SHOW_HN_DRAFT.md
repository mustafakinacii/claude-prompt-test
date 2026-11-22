# Show HN draft

**Title:** Show HN: claude-prompt-test, unit tests for prompts (YAML cases, assertions, CI exit codes)

**Body:**

Prompts break silently. When I change a sentence in a prompt or switch model versions, nothing errors; the output just gets a bit worse, and I notice later. I wanted something like pytest for that, with as little machinery as possible.

claude-prompt-test is a small Python CLI. You write a `prompts.yaml` with a prompt template (`{{vars}}`), an optional system prompt, a model, and test cases. Each case has assertions: contains, not_contains, regex, max_words, is_json (+ required keys), starts_with, equals, and an optional LLM-judge rubric (a second Claude call, off by default). `claude-prompt-test run prompts.yaml` prints a pass/fail table with latency and tokens per case and exits 1 on failure, so it drops into CI. `--repeat N` re-runs each case to flag flaky prompts, `--concurrency` parallelizes, `--json` gives machine output. Cost is shown only if you pass your own per-million prices; nothing is hardcoded.

It is deliberately minimal: two dependencies (anthropic, pyyaml), a Provider interface so tests run offline against a fake, and a `--dry-run` mode to validate your YAML without a key.

Honest status:

- The test suite (58 tests) passes, but only against the fake provider.
- The real Anthropic provider has not been run against the live API yet; I had no API key while building it. It is written against the installed SDK's signatures. Expect rough edges, and I would appreciate bug reports from anyone who tries it.
- Text-in/text-out only: no tools, images, multi-turn, or streaming.
- LLM-judge assertions are themselves non-deterministic.
- Independent project, not affiliated with Anthropic. Only supports Claude for now.

Repo: https://github.com/mustafakinacii/claude-prompt-test

Questions I would like feedback on: what assertions do you actually want that are missing, and is YAML the right format or would you rather write these in Python?
