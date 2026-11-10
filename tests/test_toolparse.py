"""Regression fixtures for the shared Python tool protocol parser."""

import itertools
import json
import re

import pytest

from desktop.toolparse import has_unterminated, parse_tool_calls, strip_tool_blocks


def fence(body, label="chatbridge-tool-call", close=True):
    return f"```{label}\n{body}\n" + ("```" if close else "")


def request(tool="read_file", args=None, **extra):
    return json.dumps({"tool": tool, "args": {"path": "src/app.py"} if args is None else args, **extra}, ensure_ascii=False)


def actual(text, final=True):
    return [call for call in parse_tool_calls(text, final) if call["tool"] != "__parse_error__"]


def errors(text, final=True):
    return [call["args"]["reason"] for call in parse_tool_calls(text, final) if call["tool"] == "__parse_error__"]


def tag(name, closing=False, sep="｜", left=None, right=None, attrs=""):
    return f"<{'/' if closing else ''}{left or sep}DSML{right or sep}{name}{(' ' + attrs) if attrs else ''}>"


def dsml(tool="read_file", parameters=None, container="tool_calls", sep="｜", invoke_close=True):
    if parameters is None:
        parameters = [("path", "true", "src/app.py", True)]
    text = tag(container, sep=sep) + tag("invoke", sep=sep, attrs=f'name="{tool}" id="ds-1"')
    for name, string, value, closed in parameters:
        text += tag("parameter", sep=sep, attrs=f'name="{name}" string="{string}"') + value
        if closed:
            text += tag("parameter", closing=True, sep=sep)
    if invoke_close:
        text += tag("invoke", closing=True, sep=sep)
    return text + tag(container, closing=True, sep=sep)


@pytest.mark.parametrize("label", ["chatbridge", "chatbridge-tool-call"])
def test_canonical_labels_and_optional_id(label):
    calls = parse_tool_calls("I will inspect it.\n" + fence(request(), label) + "\nThen continue.")
    assert len(calls) == 1
    assert calls[0]["tool"] == "read_file"
    assert calls[0]["args"] == {"path": "src/app.py"}
    assert re.fullmatch(r"t_[0-9a-f]{32}", calls[0]["id"])


def test_explicit_id_is_preserved_and_generated_ids_are_unique():
    assert actual(fence(request(id="known-id")))[0]["id"] == "known-id"
    calls = actual(fence(request()) + "\n" + fence(request()))
    assert len({call["id"] for call in calls}) == 2


@pytest.mark.parametrize("identifier", [None, 7, {}, "", "  "])
def test_invalid_id_is_replaced(identifier):
    assert actual(fence(request(id=identifier)))[0]["id"].startswith("t_")


def test_line_fences_whitespace_extra_ticks_and_crlf():
    text = '  `````  chatbridge-tool-call  \r\n' + request() + '\r\n  ````\r\nAfter'
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == "After"
    assert not has_unterminated(text)


@pytest.mark.parametrize("tool", ["read_file", "write_file", "list_dir", "search_files", "run_command"])
def test_all_supported_names_are_left_canonical(tool):
    assert actual(fence(request(tool)))[0]["tool"] == tool


@pytest.mark.parametrize("tool", ["custom_tool", "vendor.read", "mcp:query", "unknown-tool", "ابزار", "x" * 64])
def test_unknown_healthy_names_preserved_for_executor_steering(tool):
    assert actual(fence(request(tool)))[0]["tool"] == tool
    assert not errors(fence(request(tool)))


@pytest.mark.parametrize("tool", ["", " ", "read_file ", "[object Object]", {}, [], None, 1, True, "x" * 65, "a/b", "a b", '{"tool":"read_file"}', "foo\nbar"])
def test_unhealthy_tool_names_never_dispatch(tool):
    text = fence(request(tool))
    assert not actual(text)
    assert errors(text) == ["invalid-tool-name"]
    assert strip_tool_blocks(text) == ""


def test_model_authored_parse_error_is_rejected_not_trusted():
    text = fence(request("__parse_error__", {"reason": "model-injected-reason"}))
    assert parse_tool_calls(text)[0]["args"] == {"reason": "reserved-tool-name"}
    assert parse_tool_calls(text, final=False) == []


def test_multiple_calls_in_response_and_in_one_fence_keep_source_order():
    text = fence(request("read_file", id="one") + '\n' + request("list_dir", id="two")) + '\n' + dsml("run_command", [("cmd", "true", "pwd", True)])
    assert [call["tool"] for call in actual(text)] == ["read_file", "list_dir", "run_command"]
    assert [call["id"] for call in actual(text)][:2] == ["one", "two"]


def test_array_of_calls_is_supported_without_dispatching_nested_tool_dicts():
    text = fence(json.dumps([{"tool": "read_file", "args": {}}, {"tool": "list_dir", "args": {}}]))
    assert [call["tool"] for call in actual(text)] == ["read_file", "list_dir"]
    assert not actual(fence('{"wrapper":{"tool":"run_command","args":{"cmd":"bad"}}}'))


def test_brace_matcher_handles_strings_escapes_nested_data_and_trailing_prose():
    content = 'quote " and \\ path, } { [ ] ``` and nested JSON {"tool":"run_command"}'
    text = fence(request("write_file", {"content": content, "path": "test.txt", "nested": {"a": [1, {"b": "}"}]}}) + '\nExplanatory prose with no required lookahead.')
    assert actual(text)[0]["args"]["content"] == content
    assert len(actual(text)) == 1


def test_json_before_fence_closer_may_have_trailing_text():
    text = fence(request() + "\nI will use the result next.") + "\nDone."
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == "Done."


@pytest.mark.parametrize("control", ["\n", "\r", "\t", "\x00", "\x01", "\x08", "\x0b", "\x0c", "\x1f"])
def test_raw_control_character_repair_inside_json_strings(control):
    raw = '{"tool":"write_file","args":{"path":"a.txt","content":"first' + control + 'second"}}'
    assert actual(fence(raw))[0]["args"]["content"] == "first" + control + "second"


def test_raw_controls_plus_trailing_commas_zai_fixture():
    # z.ai splits one response across assistant nodes, introducing raw newlines.
    raw = '{"tool":"write_file","args":{"path":"src/demo.py","content":"def demo():\n\treturn {\"ok\": True}\n",},}'
    # Quotes in the source code must remain JSON-escaped; the raw controls do not.
    raw = raw.replace('{"ok": True}', '{\\"ok\\": True}')
    call = actual(fence(raw))[0]
    assert call["args"]["content"] == 'def demo():\n\treturn {"ok": True}\n'
    assert not errors(fence(raw))


def test_raw_newline_after_backslash_can_be_repaired():
    raw = '{"tool":"write_file","args":{"content":"before\\\nafter"}}'
    assert actual(fence(raw))[0]["args"]["content"] == "before\nafter"


def test_comma_repair_does_not_change_quoted_commas():
    text = fence('{"tool":"write_file","args":{"content":",} ,]", "items":[1,2,],},}')
    assert actual(text)[0]["args"] == {"content": ",} ,]", "items": [1, 2]}


@pytest.mark.parametrize("mark", list("\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"))
@pytest.mark.parametrize("escaped", [False, True])
def test_bidi_marks_are_removed_from_labels_names_keys_and_paths(mark, escaped):
    path = "مسیر\u200cفارسی/file.txt"
    body = request("read_" + mark + "file", {"pa" + mark + "th": mark + path})
    if escaped:
        body = body.replace(mark, f"\\u{ord(mark):04x}")
    text = fence(body, "chat" + mark + "bridge-tool-call")
    assert actual(text)[0]["args"] == {"path": path}
    assert actual(text)[0]["tool"] == "read_file"


def test_zwnj_is_preserved_in_prose_and_json_values():
    prose = "نیم\u200cفاصله"
    text = prose + "\n" + fence(request(args={"path": prose}))
    assert strip_tool_blocks(text) == prose
    assert actual(text)[0]["args"]["path"] == prose


@pytest.mark.parametrize("body,reason", [("", "tool-json-empty"), ("not JSON", "tool-json-empty"), ('{"tool":', "tool-json-incomplete"), ('{"tool":"read_file", broken}', "tool-json-invalid"), ('{"args":{}}', "tool-json-missing-tool"), ('[]', "tool-json-empty")])
def test_final_invalid_fences_produce_explicit_parser_error(body, reason):
    assert errors(fence(body)) == [reason]
    assert not actual(fence(body))
    assert strip_tool_blocks(fence(body)) == ""


@pytest.mark.parametrize("args", [[], None, 1, True, "bad JSON"])
def test_args_must_be_a_json_object(args):
    assert errors(fence(request(args=args) if args is not None else '{"tool":"read_file","args":null}')) == ["invalid-tool-args"]


def test_string_encoded_args_and_missing_args_are_safe_objects():
    assert actual(fence(request(args='{"path":"a",}')))[0]["args"] == {"path": "a"}
    assert actual(fence('{"tool":"read_file"}'))[0]["args"] == {}


def test_non_json_constants_are_not_accepted():
    assert errors(fence('{"tool":"read_file","args":{"path":NaN}}')) == ["tool-json-invalid"]


def test_bad_call_does_not_silence_good_call_in_same_block():
    text = fence(request("read_file") + '\n' + request("[object Object]"))
    assert len(actual(text)) == 1
    assert errors(text) == ["invalid-tool-name"]


@pytest.mark.parametrize("label", ["chatbridge-tool-result", "chatbridge-tool-result extra"])
def test_result_fences_never_execute_even_if_payload_has_tool(label):
    text = "Before\n" + fence(request("run_command"), label) + "\nAfter"
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == "Before\nAfter"


def test_unfenced_result_banner_is_hidden_and_never_executed():
    text = "chatbridge-tool-result\n" + request("run_command") + "\n```\nVisible"
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == "Visible"


@pytest.mark.parametrize("body", ['{"tool":"read_file","args":', '{"tool":read_file,"args":{}}', "{'tool':'read_file','args':{}}", '{“tool”:“read_file”,“args”:{}}', request()])
def test_naked_taught_fragments_error_instead_of_execute(body):
    text = "Before\n" + body + "\n"
    assert not actual(text)
    assert errors(text) == ["tool-json-fragment"]
    assert strip_tool_blocks(text) == "Before"
    assert parse_tool_calls(text, final=False) == []


def test_naked_complete_fragment_preserves_surrounding_inline_prose():
    text = "Before " + request() + " After."
    assert strip_tool_blocks(text) == "Before  After."
    assert not has_unterminated(text)


def test_naked_incomplete_fragment_preserves_following_natural_prose():
    text = 'Before\n{"tool":"read_file","args":\nPlease retry the request.'
    assert strip_tool_blocks(text) == "Before\nPlease retry the request."
    assert has_unterminated(text)


@pytest.mark.parametrize("text", [
    '```json\n{"tool":"read_file","args":{}}\n```',
    '```python\nprint("chatbridge-tool-call")\n```',
    '````markdown\n```chatbridge-tool-call\n{"tool":"read_file","args":{}}\n```\n````',
    'Inline `{"tool":"read_file","args":{}}` example.',
    'Use `chatbridge-tool-call` for requests.',
    'We use chatbridge-tool-call blocks, not tool-result blocks.',
    'Ordinary JSON {"answer":{"a":[1,2]}} and prose.',
    '```xml\n<｜DSML｜invoke name="run_command"></invoke>\n```',
    '<div>Normal HTML</div>',
])
def test_normal_prose_and_code_remain_unchanged_and_never_dispatch(text):
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == text
    assert not has_unterminated(text)


def test_broken_banner_with_language_fence_is_rescued():
    text = 'Before\nchatbridge-tool-call\n```json\n' + request() + '\n```\nAfter'
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == "Before\nAfter"


def test_broken_label_with_inline_payload_is_rescued():
    text = '```chatbridge-tool-call ' + request() + '\n```\nAfter'
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == "After"


def test_real_zai_renderer_split_fence_fixture():
    text = 'Before\n```chatbridge-tool-call\n{"tool":"write_file","args":{"path":"a.py","content":"first\n```\n```text\nsecond\n"}}\n```\nAfter'
    calls = actual(text)
    assert len(calls) == 1
    assert calls[0]["args"]["content"] == "first\nsecond\n"
    assert strip_tool_blocks(text) == "Before\nAfter"


def test_claude_split_fence_and_bare_banner_fixture():
    text = 'Before\n```\nchatbridge\n' + request() + '\n```\nAfter'
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == "Before\nAfter"


def test_unclosed_fence_final_rescues_complete_json_but_stream_defers_it():
    text = fence(request(), close=False)
    assert has_unterminated(text)
    assert not parse_tool_calls(text, final=False)
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == ""


def test_unclosed_fence_keeps_prose_after_complete_request():
    text = fence(request(), close=False) + "I will inspect the result next."
    assert strip_tool_blocks(text) == "I will inspect the result next."
    assert has_unterminated(text)


def test_stream_complete_block_and_incomplete_second_block():
    first = fence(request("read_file", id="one"))
    second = fence('{"tool":"write_file","args":', close=False)
    text = first + '\nVisible\n' + second
    assert [call["id"] for call in parse_tool_calls(text, final=False)] == ["one"]
    assert has_unterminated(text)
    assert errors(text) == ["tool-json-incomplete"]
    assert strip_tool_blocks(text) == "Visible"


def test_new_opener_does_not_close_or_swallow_previous_unclosed_request():
    text = fence(request("read_file"), close=False) + fence(request("list_dir"))
    assert [call["tool"] for call in actual(text)] == ["read_file", "list_dir"]
    assert [call["tool"] for call in actual(text, final=False)] == ["list_dir"]
    assert has_unterminated(text)


@pytest.mark.parametrize("container", ["tool_calls", "calls"])
@pytest.mark.parametrize("sep", ["｜", "｜｜", "|", "||", "![", "]"])
def test_dsml_variations_and_container_alias(container, sep):
    text = "Before\n" + dsml(container=container, sep=sep) + "\nAfter"
    assert actual(text)[0] == {"id": "ds-1", "tool": "read_file", "args": {"path": "src/app.py"}}
    assert strip_tool_blocks(text) == "Before\n\nAfter"
    assert not has_unterminated(text)


@pytest.mark.parametrize("left,right", list(itertools.product(["｜", "｜｜", "|", "![", "]"], repeat=2)))
def test_dsml_separator_variants_on_both_sides(left, right):
    text = tag("calls", left=left, right=right) + tag("invoke", left=left, right=right, attrs='name="read_file"') + '</invoke>' + tag("calls", closing=True, left=left, right=right)
    assert actual(text)[0]["tool"] == "read_file"
    assert not has_unterminated(text)


@pytest.mark.parametrize("name", ["terminal", "bash", "shell", "execute_command", "run_terminal_cmd"])
def test_dsml_command_aliases(name):
    text = dsml(name, [("command", "true", "pwd", True)])
    assert actual(text)[0]["tool"] == "run_command"
    assert actual(text)[0]["args"] == {"cmd": "pwd"}


def test_aliases_are_not_applied_to_canonical_unknown_names():
    assert actual(fence(request("terminal")))[0]["tool"] == "terminal"


def test_dsml_types_and_declared_raw_strings():
    text = dsml(parameters=[("path", "true", "src/app.py", True), ("offset", "false", "2", True), ("limit", "false", "10", True), ("flag", "false", "true", True), ("items", "false", '[1,2,]', True), ("nothing", "false", "null", True)])
    assert actual(text)[0]["args"] == {"path": "src/app.py", "offset": 2, "limit": 10, "flag": True, "items": [1, 2], "nothing": None}


@pytest.mark.parametrize("name", ["args", "arguments", "input"])
@pytest.mark.parametrize("encoded", [False, True])
def test_dsml_string_json_argument_object_repair(name, encoded):
    raw = '{"path":"src/app.py", "content":"first\nsecond",}'
    value = json.dumps(raw) if encoded else raw
    text = dsml("write_file", [(name, "true", value, True)])
    assert actual(text)[0]["args"] == {"path": "src/app.py", "content": "first\nsecond"}


def test_dsml_missing_invoke_closer_is_terminated_by_container():
    text = dsml(invoke_close=False)
    assert actual(text)[0]["args"] == {"path": "src/app.py"}
    assert not has_unterminated(text)
    assert actual(text, final=False)[0]["tool"] == "read_file"


@pytest.mark.parametrize("string,value", [("false", '{"path":"a",}'), ("true", '"a"'), ("true", json.dumps('{"path":"a"}'))])
def test_dangling_parameter_with_complete_json_is_rescued(string, value):
    text = dsml(parameters=[("args" if value.startswith("{") or value.startswith('"{') else "path", string, value, False)], invoke_close=False)
    assert actual(text)[0]["args"] == {"path": "a"}
    assert not has_unterminated(text)


@pytest.mark.parametrize("string,value", [("false", '{"path":'), ("true", "unquoted text"), ("false", "not JSON")])
def test_dangling_parameter_without_json_is_dropped_for_executor_error(string, value):
    text = dsml(parameters=[("path", string, value, False)], invoke_close=False)
    assert actual(text)[0]["args"] == {}
    assert not has_unterminated(text)
    assert strip_tool_blocks(text) == ""


def test_invalid_closed_non_string_parameter_is_dropped_without_crash():
    text = dsml(parameters=[("offset", "false", "not JSON", True)])
    assert actual(text)[0]["args"] == {}


def test_dsml_multiple_invokes_missing_first_closer():
    text = tag("calls") + tag("invoke", attrs='name="read_file"') + tag("parameter", attrs='name="path" string="true"') + 'a' + tag("parameter", closing=True) + tag("invoke", attrs='name="list_dir"') + '</invoke>' + tag("calls", closing=True)
    assert [call["tool"] for call in actual(text)] == ["read_file", "list_dir"]
    assert not has_unterminated(text)


def test_dsml_plain_inner_tags_and_dangling_plain_invoke_closer_are_stripped():
    text = tag("calls") + '<invoke name="read_file"><parameter name="path" string="true">a</parameter></invoke>' + tag("calls", closing=True) + '</invoke>\nAfter'
    assert actual(text)[0]["args"] == {"path": "a"}
    assert strip_tool_blocks(text) == "After"


@pytest.mark.parametrize("body", [tag("calls") + tag("calls", closing=True), tag("tool_calls") + tag("tool_calls", closing=True), tag("parameter", attrs='name="args"') + '{}' + tag("parameter", closing=True)])
def test_dsml_empty_complete_shell_is_a_parse_error(body):
    assert errors(body) == ["dsml-empty"]
    assert not actual(body)
    assert strip_tool_blocks(body) == ""


@pytest.mark.parametrize("name", ["", "[object Object]", "bad/tool", "__parse_error__"])
def test_dsml_unhealthy_and_reserved_names_never_dispatch(name):
    assert not actual(dsml(name))
    assert errors(dsml(name))


def test_dsml_unknown_healthy_name_kept_for_steering():
    assert actual(dsml("custom.name"))[0]["tool"] == "custom.name"


def test_dsml_partial_container_and_invoke_streams_are_deferred():
    text = dsml()
    closer = tag("tool_calls", closing=True)
    partial = text[:-len(closer)]
    assert has_unterminated(partial)
    assert parse_tool_calls(partial, final=False) == []
    assert actual(partial)[0]["args"] == {"path": "src/app.py"}
    assert not has_unterminated(text)
    standalone = tag("invoke", attrs='name="read_file"')
    assert has_unterminated(standalone)
    assert not has_unterminated(standalone + '</invoke>')


def test_dsml_stream_stops_mid_first_tag():
    text = 'Before\n<｜DSML｜invoke name="read_f'
    assert has_unterminated(text)
    assert parse_tool_calls(text, final=False) == []
    assert errors(text) == ["dsml-empty"]
    assert strip_tool_blocks(text) == "Before"


def test_partial_stream_character_by_character_never_reports_error_or_executes_early():
    for text in (fence(request()), dsml()):
        for end in range(len(text)):
            calls = parse_tool_calls(text[:end], final=False)
            assert not any(call["tool"] == "__parse_error__" for call in calls)
            if has_unterminated(text[:end]):
                assert not calls
        assert len(actual(text, final=False)) == 1


def test_deep_json_is_handled_safely_without_recursive_brace_matching():
    text = fence('{"tool":"read_file","args":{"nested":' + '[' * 1500 + '0' + ']' * 1500 + '}}')
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    if calls[0]["tool"] == "__parse_error__":
        assert calls[0]["args"]["reason"] == "tool-json-invalid"
    else:
        nested = calls[0]["args"]["nested"]
        for _ in range(1500):
            nested = nested[0]
        assert nested == 0
    assert strip_tool_blocks(text) == ""


def test_large_response_is_not_truncated():
    content = "x" * 100_000 + "tail"
    text = fence(request("write_file", {"path": "a", "content": content}))
    assert actual(text)[0]["args"]["content"] == content
    assert strip_tool_blocks(text) == ""


def test_strip_is_idempotent_and_keeps_prose_mixed_with_contract_forms():
    text = "Start.\n" + fence(request()) + '\nMiddle.\n' + dsml() + '\nNext.\n' + request() + '\nEnd.'
    stripped = strip_tool_blocks(text)
    assert all(word in stripped for word in ("Start.", "Middle.", "Next.", "End."))
    assert 'chatbridge-tool-call' not in stripped and 'DSML' not in stripped
    assert strip_tool_blocks(stripped) == stripped


def test_empty_input():
    assert parse_tool_calls("") == []
    assert strip_tool_blocks("") == ""
    assert not has_unterminated("")


@pytest.mark.parametrize("label", ["chatbridgeish", "chatbridge-example", "chatbridge-tool-callback", "chatbridge-tool-call-extra", "chatbridge-tool-results", "CHATBRIDGE-TOOL-CALL"])
def test_similarly_named_non_contract_fences_remain_normal_code(label):
    text = fence(request(), label)
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == text
    assert not has_unterminated(text)


@pytest.mark.parametrize("label", ["chatbridge-tool-r", "chatbridge-tool-res", "chatbridge-tool-resul"])
def test_partial_result_label_is_never_a_call(label):
    text = fence(request("run_command"), label, close=False)
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == ""
    assert has_unterminated(text)


@pytest.mark.parametrize("raw", ["123", "true", "false", "null", "  text with whitespace\n\n", ""])
def test_dsml_string_flag_keeps_scalar_text_and_whitespace(raw):
    text = dsml("write_file", [("content", "true", raw, True)])
    assert actual(text)[0]["args"]["content"] == raw


def test_dsml_outer_quote_drift_with_unescaped_string_json():
    text = dsml("write_file", [("args", "true", '"{"path":"a","content":"line1\nline2",}"', True)])
    assert actual(text)[0]["args"] == {"path": "a", "content": "line1\nline2"}


@pytest.mark.parametrize("prefix", ["<｜DSML", "<｜｜DSML", "<|DSML", "<![DSML", "<]DSML"])
def test_stream_partial_dsml_marker_is_hidden_and_deferred(prefix):
    text = "Visible\n" + prefix
    assert has_unterminated(text)
    assert parse_tool_calls(text, final=False) == []
    assert strip_tool_blocks(text) == "Visible"


def test_dsml_attributes_allow_single_quotes_unquoted_values_and_case():
    text = '<|DSML|CALLS><|DSML|INVOKE NAME=read_file><|DSML|PARAMETER NAME=path STRING=TRUE>a</parameter></invoke></calls>'
    assert actual(text)[0]["args"] == {"path": "a"}
    assert not has_unterminated(text)
    assert strip_tool_blocks(text) == ""


def test_unrelated_json_containing_nested_tool_data_is_not_a_naked_call():
    text = 'Data: {"metadata":{"tool":"hammer","args":{"weight":2}}}. Keep this.'
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == text


def test_reason_list_is_deduplicated_and_comma_joined():
    text = fence('{}\n{}\n{"tool":"a/b","args":{}}')
    assert errors(text) == ["tool-json-missing-tool,invalid-tool-name"]


def test_unclosed_result_and_invalid_fence_do_not_hide_later_prose():
    text = 'Before\n```chatbridge-tool-result\n' + request() + '\nAfter'
    assert parse_tool_calls(text) == []
    assert strip_tool_blocks(text) == "Before\n\nAfter"
    assert has_unterminated(text)


def test_no_lookahead_regex_is_needed_to_match_root_before_arbitrary_tail():
    text = fence(request() + '\nnot-json <<< arbitrary tail : 123')
    assert actual(text)[0]["tool"] == "read_file"


def test_strip_never_leaks_malformed_tagged_payloads():
    fixtures = [
        fence('{"tool":[object Object],"args":{}}'),
        fence('{"tool":"read_file",}'),
        fence('{"tool":"read_file","args":'),
        '```chatbridge-tool-call\n```\n' + request() + '\n```',
        dsml("[object Object]"),
        '<｜DSML｜calls><｜DSML｜invoke name="read_file"><｜DSML｜parameter name="path" string="false">{"path":</calls>',
    ]
    for text in fixtures:
        assert strip_tool_blocks(text) == ""
        assert parse_tool_calls(text)


@pytest.mark.parametrize("raw", [
    '{"id":"t1","tool":"read_file","args":{}}',
    '{"id":"t1","tool":"read_file","args":',
    '{"args":{},"tool":"read_file"}',
    '{"metadata":{"value":1},"tool":"read_file","args":{}}',
])
def test_naked_taught_root_is_detected_regardless_of_member_order(raw):
    text = "Before\n" + raw
    assert actual(text) == []
    assert errors(text) == ["tool-json-fragment"]
    assert strip_tool_blocks(text) == "Before"


def test_rescue_finds_real_tool_after_empty_root_and_renderer_fences():
    text = 'Before\n```chatbridge-tool-call\n{}\n```\nThe actual request follows.\n```json\n' + request() + '\n```\nAfter'
    assert len(actual(text)) == 1
    assert actual(text)[0]["tool"] == "read_file"
    assert strip_tool_blocks(text) == "Before\nAfter"


def test_rescue_ignores_non_tool_objects_in_broken_labeled_body():
    text = 'chatbridge-tool-call\n```\n{"status":"starting"}\n' + request() + '\n```\nAfter'
    assert len(actual(text)) == 1
    assert not errors(text)
    assert strip_tool_blocks(text) == "After"
