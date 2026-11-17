"""The outbound contract stays ordinary: no tool vocabulary reaches the web chat."""
import json

from desktop.toolparse import extract_requests, strip_tool_blocks


def test_plain_fence_without_any_label_is_a_request():
    text = 'I will inspect it.\n```json\n{"tool":"read_file","args":{"path":"src/app.py"}}\n```\nDone.'
    requests = extract_requests(text)
    assert [r["tool"] for r in requests] == ["read_file"]
    assert requests[0]["args"] == {"path": "src/app.py"}
    # The request block never survives into the visible answer.
    assert requests[0]["prose"] == "I will inspect it.\nDone."
    assert "read_file" not in requests[0]["prose"]


def test_bare_fence_and_legacy_label_still_parse():
    bare = 'Sure.\n```\n{"tool":"list_dir","args":{"path":"."}}\n```'
    assert [r["tool"] for r in extract_requests(bare)] == ["list_dir"]
    legacy = 'Here.\n```chatbridge-tool-call\n{"tool":"write_file","args":{"path":"x","content":"y"}}\n```'
    assert [r["tool"] for r in extract_requests(legacy)] == ["write_file"]


def test_ordinary_code_and_prose_are_not_requests():
    text = 'A normal answer.\n```json\n{"answer":{"a":[1,2]}}\n```\nand prose.'
    assert extract_requests(text) == []
    assert strip_tool_blocks(text) == text


def test_one_at_a_time_rule_is_default_and_first_person():
    from desktop.config import DEFAULT_RULES
    rule = next(row for row in DEFAULT_RULES if row["id"] == "one-at-a-time")
    assert rule["enabled"] is True and rule["builtin"] is True
    assert rule["text"].startswith("I ")
    assert "one at a time" in rule["text"]
