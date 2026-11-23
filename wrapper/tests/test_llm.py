import json

import pytest
from rail_rag import prompts
from rail_rag.graph import passage_numbers
from rail_rag.providers import LLMUnavailable, parse_json

from rail_k8s.llm import DeadlineLLM, FakeLLM

PASSAGES = "Question: q\n\nPassages:\n" + prompts.numbered_passages(["a", "b", "c", "d"])


def fake(**kw):
    return FakeLLM(sleep=lambda s: None, **kw)


def test_delay_is_in_range_and_repeatable():
    a, b = fake(min_ms=300, max_ms=900, seed=1), fake(min_ms=300, max_ms=900, seed=1)
    delays = [a.delay_seconds(prompts.REWRITE, f"question {i}") for i in range(200)]
    assert all(0.3 <= d <= 0.9 for d in delays)
    assert delays == [b.delay_seconds(prompts.REWRITE, f"question {i}") for i in range(200)]
    assert max(delays) - min(delays) > 0.4  # spread over the range, not a constant


def test_seed_changes_delays():
    d0 = fake(seed=0).delay_seconds("s", "u")
    assert d0 != fake(seed=1).delay_seconds("s", "u")


def test_sleeps_the_computed_delay():
    slept = []
    llm = FakeLLM(sleep=slept.append)
    llm.complete(prompts.REWRITE, "what?")
    assert slept == [llm.delay_seconds(prompts.REWRITE, "what?")]


def test_rewrite_returns_the_question():
    assert fake().complete(prompts.REWRITE, "What is a TSI?") == "What is a TSI?"


def test_grade_reply_is_what_upstream_parses():
    reply = fake().complete(prompts.GRADE, PASSAGES, schema=prompts.GRADE_SCHEMA)
    assert passage_numbers(parse_json(reply)["relevant"]) == [1, 2, 3]


def test_grade_with_no_passages_is_empty():
    reply = fake().complete(prompts.GRADE, "Question: q\n\nPassages:\n", schema=prompts.GRADE_SCHEMA)
    assert parse_json(reply)["relevant"] == []


def test_generate_reply_cites_a_passage():
    reply = json.loads(fake().complete(prompts.GENERATE, PASSAGES, schema=prompts.GENERATE_SCHEMA))
    assert reply["insufficient"] is False and "[1]" in reply["answer"]


def test_bad_range_rejected():
    with pytest.raises(ValueError):
        FakeLLM(min_ms=900, max_ms=300)


def test_deadline_turns_a_slow_call_into_llm_unavailable():
    import time

    class Slow:
        name = "slow"

        def complete(self, system, user, *, schema=None):
            time.sleep(0.5)
            return "late"

    with pytest.raises(LLMUnavailable):
        DeadlineLLM(Slow(), timeout_seconds=0.05).complete("s", "u")


def test_deadline_passes_a_fast_call_through():
    class Fast:
        name = "fast"

        def complete(self, system, user, *, schema=None):
            return "ok"

    assert DeadlineLLM(Fast(), timeout_seconds=1).complete("s", "u") == "ok"
