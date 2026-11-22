import json

import pytest

from claude_prompt_test.assertions import check_deterministic, parse_json_output
from claude_prompt_test.cli import main
from claude_prompt_test.providers import FakeProvider, ProviderError
from claude_prompt_test.runner import run_all, summarize
from claude_prompt_test.spec import SpecError, parse_spec, render


def spec_with(assertions: str, extra_top: str = "") -> str:
    return f"""
prompt: "Say hi to {{{{name}}}}"
{extra_top}
tests:
  - name: t
    vars: {{name: Bob}}
    assert:
{assertions}
"""


def run_text(output, assertions_yaml, judge=False, responder=None):
    spec = parse_spec(spec_with(assertions_yaml))
    fake = FakeProvider(responder or (lambda s, p, purpose: output if purpose == "test"
                                      else "PASS\nok"))
    return run_all(spec, fake, use_judge=judge)[0]


# ---- every assertion type: pass and fail ----------------------------------

@pytest.mark.parametrize("assertion,output,ok", [
    ("contains: hello", "well hello there", True),
    ("contains: hello", "nope", False),
    ("contains: [a, b]", "a and b", True),
    ("contains: [a, b]", "only a", False),
    ("not_contains: bad", "good", True),
    ("not_contains: bad", "very bad", False),
    ("regex: '^\\d{3}$'", "123", True),
    ("regex: '^\\d{3}$'", "12a", False),
    ("max_words: 3", "one two three", True),
    ("max_words: 3", "one two three four", False),
    ("is_json: true", '{"a": 1}', True),
    ("is_json: true", "not json", False),
    ("is_json: true", '```json\n{"a": 1}\n```', True),
    ("json_has_keys: [a, b]", '{"a": 1, "b": 2}', True),
    ("json_has_keys: [a, b]", '{"a": 1}', False),
    ("json_has_keys: [a]", "[1, 2]", False),
    ("json_has_keys: [a]", "garbage", False),
    ("starts_with: Hello", "  Hello world", True),
    ("starts_with: Hello", "Oh Hello", False),
    ("equals: done", " done\n", True),
    ("equals: done", "done.", False),
])
def test_assertions(assertion, output, ok):
    r = run_text(output, "      " + assertion)
    assert r.passed is ok
    assert bool(r.failures) is (not ok)


def test_multiple_failures_are_all_reported():
    r = run_text("x", "      contains: a\n      max_words: 0\n      equals: y")
    assert len(r.failures) == 3


def test_parse_json_output_fence():
    assert parse_json_output('```\n[1]\n```') == [1]


# ---- llm_judge -------------------------------------------------------------

def test_judge_off_by_default_makes_no_second_call():
    spec = parse_spec(spec_with('      llm_judge: "be nice"'))
    fake = FakeProvider(lambda s, p, purpose: "out")
    res = run_all(spec, fake)[0]
    assert res.passed and [c["purpose"] for c in fake.calls] == ["test"]


def test_judge_pass_and_fail_and_unparseable():
    ok = run_text("out", '      llm_judge: "be nice"', judge=True)
    assert ok.passed
    bad = run_text("out", '      llm_judge: "be nice"', judge=True,
                   responder=lambda s, p, pu: "out" if pu == "test" else "FAIL\ntoo rude")
    assert not bad.passed and "too rude" in bad.failures[0]
    junk = run_text("out", '      llm_judge: "be nice"', judge=True,
                    responder=lambda s, p, pu: "out" if pu == "test" else "maybe?")
    assert not junk.passed and "unparseable" in junk.failures[0]


def test_judge_uses_judge_model_and_counts_tokens():
    spec = parse_spec(spec_with('      llm_judge: "x"', 'judge_model: judge-m\nmodel: main-m'))
    fake = FakeProvider(lambda s, p, pu: "out" if pu == "test" else "PASS")
    res = run_all(spec, fake, use_judge=True)[0]
    assert [c["model"] for c in fake.calls] == ["main-m", "judge-m"]
    assert res.input_tokens > len(fake.calls[0]["prompt"].split())


# ---- templating, system prompt --------------------------------------------

def test_render_and_prompt_passed_to_provider():
    spec = parse_spec(spec_with("      contains: x", "system: 'You are {{ name }}'"))
    fake = FakeProvider(lambda s, p, pu: "x")
    run_all(spec, fake)
    assert fake.calls[0]["prompt"] == "Say hi to Bob"
    assert fake.calls[0]["system"] == "You are Bob"
    assert fake.calls[0]["model"] == "claude-haiku-5-5"


def test_render_missing_var():
    with pytest.raises(SpecError):
        render("{{x}}", {})


# ---- repeat / flaky / concurrency / errors ---------------------------------

def test_repeat_detects_flaky():
    spec = parse_spec(spec_with("      equals: ok"))
    n = {"i": 0}

    def responder(s, p, pu):
        n["i"] += 1
        return "ok" if n["i"] % 2 else "nope"

    results = run_all(spec, FakeProvider(responder), repeat=4)
    s = summarize(results)
    assert s["runs"] == 4 and s["passed"] == 2 and s["flaky"] == ["t"]


def test_repeat_all_fail_is_not_flaky():
    spec = parse_spec(spec_with("      equals: ok"))
    s = summarize(run_all(spec, FakeProvider(lambda *a: "no"), repeat=3))
    assert s["failed"] == 3 and s["flaky"] == []


def test_concurrency_keeps_order():
    text = """
prompt: "{{n}}"
tests:
""" + "".join(f"  - name: c{i}\n    vars: {{n: {i}}}\n    assert: {{equals: '{i}'}}\n" for i in range(8))
    spec = parse_spec(text)
    res = run_all(spec, FakeProvider(lambda s, p, pu: p), concurrency=4)
    assert [r.case for r in res] == [f"c{i}" for i in range(8)]
    assert all(r.passed for r in res)


def test_provider_error_is_a_failed_case_not_a_crash():
    spec = parse_spec(spec_with("      contains: x"))
    res = run_all(spec, FakeProvider(lambda *a: ProviderError("boom")))[0]
    assert not res.passed and res.error == "boom"


# ---- YAML / spec errors ----------------------------------------------------

@pytest.mark.parametrize("text,msg", [
    ("prompt: [unclosed", "invalid YAML"),
    ("- a\n- b", "mapping"),
    ("tests: []", "'prompt'"),
    ("prompt: hi", "'tests'"),
    ("prompt: hi\ntests: []", "'tests'"),
    ("prompt: hi\ntests: [1]", "mapping"),
    ("prompt: hi\ntests:\n  - name: a\n", "at least one assertion"),
    ("prompt: hi\ntests:\n  - name: a\n    assert: {bogus: 1}", "unknown assertion"),
    ("prompt: '{{x}}'\ntests:\n  - name: a\n    assert: {contains: a}", "missing variable"),
    ("prompt: hi\ntests:\n  - name: a\n    assert: {regex: '('}", "invalid regex"),
    ("prompt: hi\ntests:\n  - name: a\n    assert: {max_words: -1}", "max_words"),
    ("prompt: hi\ntests:\n  - name: a\n    assert: {is_json: maybe}", "is_json"),
    ("prompt: hi\nmax_tokens: 0\ntests:\n  - name: a\n    assert: {contains: a}", "max_tokens"),
    ("prompt: hi\ntests:\n  - name: a\n    assert: {contains: a}\n  - name: a\n    assert: {contains: b}",
     "duplicate"),
])
def test_spec_errors(text, msg):
    with pytest.raises(SpecError, match=msg):
        parse_spec(text)


# ---- CLI + exit codes ------------------------------------------------------

GOOD = "prompt: 'Hi {{n}}'\ntests:\n  - name: a\n    vars: {n: x}\n    assert: {contains: 'Hi x'}\n"
BAD = GOOD.replace("contains: 'Hi x'", "equals: nothing")


def write(tmp_path, text):
    p = tmp_path / "prompts.yaml"
    p.write_text(text)
    return str(p)


def test_exit_0_on_pass(tmp_path, capsys):
    assert main(["run", write(tmp_path, GOOD), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "DRY RUN" in out and "Estimated cost" not in out


def test_exit_1_on_failure(tmp_path, capsys):
    assert main(["run", write(tmp_path, BAD), "--dry-run"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_exit_2_on_yaml_error_and_missing_file(tmp_path, capsys):
    assert main(["run", write(tmp_path, "prompt: [unclosed"), "--dry-run"]) == 2
    assert main(["run", str(tmp_path / "nope.yaml"), "--dry-run"]) == 2
    assert "error:" in capsys.readouterr().err


def test_exit_2_without_api_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["run", write(tmp_path, GOOD)]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_exit_1_on_provider_error(tmp_path):
    fake = FakeProvider(lambda *a: ProviderError("down"))
    assert main(["run", write(tmp_path, GOOD)], provider=fake) == 1


def test_json_output_and_cost(tmp_path, capsys):
    code = main(["run", write(tmp_path, GOOD), "--dry-run", "--json",
                 "--price-in", "1", "--price-out", "2", "--repeat", "2"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["dry_run"] is True
    assert data["summary"]["runs"] == 2 and len(data["results"]) == 2
    expected = (data["summary"]["input_tokens"] * 1 + data["summary"]["output_tokens"] * 2) / 1e6
    assert data["summary"]["estimated_cost"] == pytest.approx(expected)


def test_no_cost_without_prices_json(tmp_path, capsys):
    main(["run", write(tmp_path, GOOD), "--dry-run", "--json"])
    assert json.loads(capsys.readouterr().out)["summary"]["estimated_cost"] is None


def test_cost_line_needs_both_prices(tmp_path, capsys):
    main(["run", write(tmp_path, GOOD), "--dry-run", "--price-in", "1"])
    assert "Estimated cost" not in capsys.readouterr().out


def test_table_repeat_and_flaky_line(tmp_path, capsys):
    n = {"i": 0}

    def responder(s, p, pu):
        n["i"] += 1
        return "Hi x" if n["i"] == 1 else "other"

    code = main(["run", write(tmp_path, GOOD), "--repeat", "2"], provider=FakeProvider(responder))
    out = capsys.readouterr().out
    assert code == 1 and "a #1" in out and "a #2" in out and "FLAKY" in out


def test_judge_flag_and_skip_note(tmp_path, capsys):
    text = GOOD.replace("{contains: 'Hi x'}", "{contains: 'Hi x', llm_judge: 'ok'}")
    f = write(tmp_path, text)
    main(["run", f, "--dry-run"])
    assert "llm_judge skipped" in capsys.readouterr().out
    fake = FakeProvider(lambda s, p, pu: p if pu == "test" else "FAIL\nnope")
    assert main(["run", f, "--judge"], provider=fake) == 1


def test_bad_repeat(tmp_path):
    assert main(["run", write(tmp_path, GOOD), "--dry-run", "--repeat", "0"]) == 2


def test_init_writes_valid_sample_and_refuses_overwrite(tmp_path, capsys):
    target = str(tmp_path / "p.yaml")
    assert main(["init", target]) == 0
    assert main(["run", target, "--dry-run"]) == 0
    assert main(["init", target]) == 2
    assert main(["init", target, "--force"]) == 0
