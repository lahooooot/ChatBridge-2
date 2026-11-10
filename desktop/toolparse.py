"""Canonical, dependency-free parser for model-authored local tool requests.

Only explicit ChatBridge fences and DeepSeek DSML may produce executable calls.
Naked taught JSON is a protocol error, not an alternate execution channel. The
same region scanner is used for parsing, stream guards, and display sanitizing.
Tool argument schemas and unknown-tool steering belong to the executor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4

__all__ = ["parse_tool_calls", "strip_tool_blocks", "has_unterminated"]

_BIDI = dict.fromkeys(map(ord, "\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"))
_NAME = re.compile(r"[\w.:-]{1,64}\Z")
_FENCE = re.compile(r"[ \t]*(`{3,})(.*)")
_CALL_OPEN = re.compile(r"\s*`{3,}\s*chatbridge(?:-tool-call)?\s*\Z")
_LABEL = re.compile(r"\s*(?:`{3,}\s*)?(chatbridge(?:-tool-(?:call|result))?)(.*)\Z")
_NAKED = re.compile(r"\{\s*[\"'\u201c\u201d]?tool[\"'\u201c\u201d]?\s*:")
_TOOL_KEY = re.compile(r"[\"'\u201c\u201d]?tool[\"'\u201c\u201d]?\s*:")
_SEPARATOR = r"(?:[|\uff5c]{1,2}|!\[|\])"
_DSML_PREFIX = re.compile(r"<\s*/?\s*" + _SEPARATOR + r"\s*DSML\b", re.I)
_DSML_TAG = re.compile(
    r"<\s*(/?)\s*(" + _SEPARATOR + r"\s*DSML\s*" + _SEPARATOR
    + r")?\s*(/?)\s*(tool_calls|calls|invoke|parameter)\b([^>]*)>", re.I
)
_ATTR = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))")
_ALIASES = dict.fromkeys(("terminal", "bash", "shell", "execute_command", "run_terminal_cmd"), "run_command")


@dataclass(frozen=True)
class _Region:
    kind: str
    start: int
    end: int
    body: str
    complete: bool


@dataclass(frozen=True)
class _Tag:
    start: int
    end: int
    name: str
    closing: bool
    marked: bool
    attrs: dict[str, str]


def _text(text: str) -> str:
    return text.translate(_BIDI)


def _is_anchor(label: re.Match[str] | None, fenced: bool) -> bool:
    if label is None:
        return False
    tail = label.group(2)
    if not tail.strip():
        return True
    if not fenced:
        return False
    if tail[0].isspace() or tail.startswith(("{", "[")):
        return True
    # An unmistakable streaming prefix may be hidden/deferred, but unrelated
    # language labels such as chatbridge-example are ordinary code fences.
    return label.group(1) == "chatbridge" and tail.startswith("-tool-") and any(
        full.startswith(tail) for full in ("-tool-call", "-tool-result")
    )


def _match_root(text: str, start: int) -> int | None:
    """Return the exclusive balanced root end using a stack and string state.

    A mismatched closer still ends the candidate if it exhausts the stack; JSON
    validation subsequently reports it as invalid, rather than guessing a call.
    No regular expression decides where a JSON object ends.
    """
    stack: list[str] = []
    quoted = escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack:
                return index + 1
            stack.pop()
            if not stack:
                return index + 1
    return None


def _roots(text: str) -> Iterator[tuple[int, int | None, str]]:
    position = 0
    while position < len(text):
        # Skip quoted prose as well as braces inside strings between roots.
        char = text[position]
        if char == '"':
            position += 1
            escaped = False
            while position < len(text):
                char = text[position]
                position += 1
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    break
            continue
        if char in "{[":
            end = _match_root(text, position)
            yield position, end, text[position:end]
            if end is None:
                return
            position = end
        else:
            position += 1


def _repair_controls(text: str) -> str:
    output: list[str] = []
    quoted = escaped = False
    for char in text:
        if quoted and ord(char) < 32:
            # A backslash immediately before a raw newline is also malformed.
            if escaped:
                output.pop()
            output.append(json.dumps(char)[1:-1])
            escaped = False
            continue
        output.append(char)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
    return "".join(output)


def _repair_commas(text: str) -> str:
    output: list[str] = []
    quoted = escaped = False
    for index, char in enumerate(text):
        if not quoted and char == ",":
            following = index + 1
            while following < len(text) and text[following].isspace():
                following += 1
            if following < len(text) and text[following] in "}]":
                continue
        output.append(char)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
    return "".join(output)


def _reject_constant(value: str) -> None:
    raise ValueError("Non-JSON constant: " + value)


def _clean_value(value: Any) -> Any:
    """Strip also JSON-escaped bidi marks, without stripping Persian ZWNJ."""
    if isinstance(value, str):
        return _text(value)
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pairs = list(item.items())
            item.clear()
            for key, child in pairs:
                key = _text(key)
                item[key] = _text(child) if isinstance(child, str) else child
                if isinstance(child, (dict, list)):
                    pending.append(child)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                if isinstance(child, str):
                    item[index] = _text(child)
                elif isinstance(child, (dict, list)):
                    pending.append(child)
    return value


def _load_json(text: str) -> Any:
    text = _text(text).strip()
    controls = _repair_controls(text)
    for candidate in (text, controls, _repair_commas(controls)):
        try:
            return _clean_value(json.loads(candidate, parse_constant=_reject_constant))
        except (ValueError, RecursionError):
            pass
    raise ValueError("Invalid JSON")


def _call(value: Any, *, dsml: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, dict) or "tool" not in value:
        return None, "tool-json-missing-tool"
    name = value["tool"]
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        return None, "invalid-tool-name"
    if name == "__parse_error__":
        return None, "reserved-tool-name"
    if dsml:
        name = _ALIASES.get(name, name)
    args = value.get("args", {})
    if isinstance(args, str):
        try:
            args = _load_json(args)
        except ValueError:
            return None, "invalid-tool-args"
    if not isinstance(args, dict):
        return None, "invalid-tool-args"
    if dsml and name == "run_command" and "cmd" not in args and "command" in args:
        args = dict(args)
        args["cmd"] = args.pop("command")
    identifier = value.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        identifier = "t_" + uuid4().hex
    return {"id": identifier, "tool": name, "args": args}, None


def _error(reasons: list[str]) -> dict[str, Any]:
    return {"id": "t_" + uuid4().hex, "tool": "__parse_error__", "args": {"reason": ",".join(dict.fromkeys(reasons))}}


def _without_fences(text: str, offset: int = 0) -> tuple[str, list[int]]:
    output: list[str] = []
    positions: list[int] = []
    position = offset
    for line in text.splitlines(keepends=True):
        if not _FENCE.fullmatch(line.rstrip("\r\n")):
            output.append(line)
            positions.extend(range(position, position + len(line)))
        position += len(line)
    return "".join(output), positions


def _extend_rescue(text: str, body_start: int, end: int) -> tuple[int, str]:
    """Rejoin JSON split by page-renderer fence lines, keeping trailing prose."""
    body = text[body_start:end]
    candidates = list(_roots(body))
    if any(root_end is not None and _taught_root(raw) for _, root_end, raw in candidates) or _parse_fence(body)[0]:
        return end, body
    # Stop before another explicit call/result: independent requests must not be
    # merged. Bare fence lines are renderer artifacts and may be removed.
    limit = len(text)
    position = body_start
    for line in text[body_start:].splitlines(keepends=True):
        match = _LABEL.fullmatch(line.rstrip("\r\n"))
        if _is_anchor(match, bool(_FENCE.fullmatch(line.rstrip("\r\n")))):
            limit = position
            break
        position += len(line)
    rescued, positions = _without_fences(text[body_start:limit], body_start)
    for root_start, root_end, raw in _roots(rescued):
        if root_end is None:
            break
        try:
            value = _load_json(raw)
        except ValueError:
            continue
        if not isinstance(value, dict) or "tool" not in value:
            continue
        new_end = max(end, positions[root_end - 1] + 1)
        # Consume a renderer's final fence only when separated by whitespace.
        tail = text[new_end:limit]
        consumed = 0
        for line in tail.splitlines(keepends=True):
            if not line.strip():
                consumed += len(line)
            elif _FENCE.fullmatch(line.rstrip("\r\n")):
                new_end += consumed + len(line)
                break
            else:
                break
        return new_end, rescued[root_start:root_end]
    return end, body


def _taught_root(raw: str) -> bool:
    """Recognize a top-level tool member even before its JSON is complete."""
    depth = 0
    quoted = escaped = False
    key_position = False
    for index, char in enumerate(raw):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if depth == 1 and key_position and _TOOL_KEY.match(raw, index):
            return True
        if char in "{[":
            depth += 1
            key_position = depth == 1 and char == "{"
        elif char in "}]":
            depth -= 1
            key_position = False
        elif char == ",":
            key_position = depth == 1
        elif not char.isspace():
            key_position = False
        if char == '"':
            quoted = True
    return False


def _fence_regions(text: str) -> tuple[list[_Region], list[tuple[int, int]]]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    regions: list[_Region] = []
    protected: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        raw = lines[index].rstrip("\r\n")
        anchor = offsets[index]
        fence = _FENCE.fullmatch(raw)
        label = _LABEL.fullmatch(raw)
        # Some renderers put the language banner immediately inside a bare
        # fence rather than on its opening line. It is still an explicit anchor.
        if fence and not fence.group(2).strip() and index + 1 < len(lines):
            banner = _LABEL.fullmatch(lines[index + 1].rstrip("\r\n"))
            if banner and not banner.group(2).strip():
                index += 1
                raw = lines[index].rstrip("\r\n")
                label = banner
                fence = None
        # A label in prose is not an opener. Bare labels and malformed fenced
        # labels are renderer rescue anchors; explicit result anchors never call.
        is_label = _is_anchor(label, bool(fence))
        if is_label:
            assert label is not None
            start = anchor
            canonical = bool(_CALL_OPEN.fullmatch(raw))
            result = label.group(1).endswith("-result") or label.group(2).startswith("-tool-r")
            kind = "result" if result else "call"
            body_start = offsets[index] + len(lines[index])
            # Malformed inline JSON after a label is still a rescue candidate.
            if label.group(2).strip():
                body_start = offsets[index] + label.start(2)
            close = index + 1
            while close < len(lines) and not _FENCE.fullmatch(lines[close].rstrip("\r\n")):
                close += 1
            complete = close < len(lines)
            end = offsets[close] if complete else len(text)
            body = text[body_start:end]
            if complete:
                next_label = _LABEL.fullmatch(lines[close].rstrip("\r\n"))
                if _is_anchor(next_label, True):
                    complete = False
                else:
                    end += len(lines[close])
            if kind == "call":
                new_end, rescued = _extend_rescue(text, body_start, end)
                if new_end > end or not canonical:
                    body = rescued
                end = new_end
            if not complete and close == len(lines):
                # An absent closer is a stream guard, not permission to hide
                # natural prose that follows an already completed JSON root.
                candidates = list(_roots(body))
                if candidates:
                    last_start, last_end, _ = candidates[-1]
                    if last_end is not None:
                        end = body_start + last_end
                    else:
                        end = _fragment_end(text, body_start + last_start)
                    body = text[body_start:end]
            regions.append(_Region(kind, start, end, body, complete))
            index += 1
            while index < len(lines) and offsets[index] < end:
                index += 1
            continue
        if fence:
            count = len(fence.group(1))
            close = index + 1
            while close < len(lines):
                candidate = _FENCE.fullmatch(lines[close].rstrip("\r\n"))
                if candidate and len(candidate.group(1)) >= count and not candidate.group(2).strip():
                    break
                close += 1
            end = offsets[close] + len(lines[close]) if close < len(lines) else len(text)
            protected.append((offsets[index], end))
            index = close + 1
        else:
            index += 1
    return regions, protected


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _tags(text: str) -> list[_Tag]:
    tags: list[_Tag] = []
    for match in _DSML_TAG.finditer(text):
        attrs = {item.group(1).lower(): next(group for group in item.groups()[1:] if group is not None)
                 for item in _ATTR.finditer(match.group(5))}
        name = match.group(4).lower()
        tags.append(_Tag(match.start(), match.end(), "calls" if name == "tool_calls" else name,
                         bool(match.group(1) or match.group(3)), bool(match.group(2)), attrs))
    return tags


def _dsml_regions(text: str, blocked: list[tuple[int, int]]) -> list[_Region]:
    tokens = _tags(text)
    regions: list[_Region] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        attached_closer = bool(token.closing and regions and not text[regions[-1].end:token.start].strip())
        if (not token.marked and not attached_closer) or _inside(token.start, blocked):
            index += 1
            continue
        if token.closing:
            regions.append(_Region("dsml-closer", token.start, token.end, "", True))
            index += 1
            continue
        end = len(text)
        complete = False
        cursor = index + 1
        while cursor < len(tokens):
            closer = tokens[cursor]
            if _inside(closer.start, blocked):
                end = min(start for start, stop in blocked if start <= closer.start < stop)
                break
            # A container closer also terminates an invoke with a missing closer.
            if closer.closing and (closer.name == token.name or closer.name == "calls"):
                end, complete = closer.end, True
                cursor += 1
                break
            if token.name != "calls" and not closer.closing and closer.name in ("calls", "invoke"):
                end = closer.start
                break
            cursor += 1
        regions.append(_Region("dsml", token.start, end, text[token.start:end], complete))
        index = cursor
    occupied = blocked + [(region.start, region.end) for region in regions]
    # Streaming can stop halfway through the very first DSML tag.
    for match in _DSML_PREFIX.finditer(text):
        if not _inside(match.start(), occupied):
            close = text.find(">", match.end())
            end = len(text) if close < 0 else close + 1
            region = _Region("dsml", match.start(), end, text[match.start():end], close >= 0)
            regions.append(region)
            occupied.append((region.start, region.end))
    return regions


def _fragment_end(text: str, start: int) -> int:
    end = _match_root(text, start)
    if end is not None:
        return end
    # Keep natural prose following an unfinished, non-string JSON member.
    position = start
    quoted = escaped = False
    for line in text[start:].splitlines(keepends=True):
        stripped = line.strip()
        if position > start and not quoted and stripped and not any(char in stripped for char in '{}[]"\':,'):
            return position
        for char in line:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
        position += len(line)
    return len(text)


def _regions(text: str) -> list[_Region]:
    regions, protected = _fence_regions(text)
    blocked = protected + [(region.start, region.end) for region in regions]
    # Inline code remains ordinary code, even if it documents tool-shaped JSON.
    for match in re.finditer(r"`+", text):
        if _inside(match.start(), blocked):
            continue
        closer = text.find(match.group(), match.end())
        if closer >= 0:
            blocked.append((match.start(), closer + len(match.group())))
    dsml = _dsml_regions(text, blocked)
    regions.extend(dsml)
    blocked.extend((region.start, region.end) for region in dsml)
    for root_start, root_end, raw in _roots(text):
        if _inside(root_start, blocked) or text[root_start] != "{":
            continue
        if _taught_root(raw):
            end = _fragment_end(text, root_start)
            regions.append(_Region("fragment", root_start, end, text[root_start:end], root_end is not None))
            blocked.append((root_start, end))
        else:
            # A nested tool key inside unrelated JSON is not a taught root call.
            blocked.append((root_start, root_end if root_end is not None else len(text)))
    for match in _NAKED.finditer(text):
        if _inside(match.start(), blocked):
            continue
        end = _fragment_end(text, match.start())
        regions.append(_Region("fragment", match.start(), end, text[match.start():end], _match_root(text[match.start():end], 0) is not None))
        blocked.append((match.start(), end))
    return sorted(regions, key=lambda region: region.start)


def _parse_fence(body: str) -> tuple[list[dict[str, Any]], list[str]]:
    calls: list[dict[str, Any]] = []
    reasons: list[str] = []
    found = False
    for _, end, raw in _roots(body):
        found = True
        if end is None:
            reasons.append("tool-json-incomplete")
            continue
        try:
            value = _load_json(raw)
        except ValueError:
            reasons.append("tool-json-invalid")
            continue
        values = value if isinstance(value, list) else [value]
        if not values:
            reasons.append("tool-json-empty")
        for item in values:
            call, reason = _call(item)
            if call is not None:
                calls.append(call)
            elif reason:
                reasons.append(reason)
    if not found:
        reasons.append("tool-json-empty")
    return calls, reasons


def _parameter(raw: str, string: bool, closed: bool) -> tuple[bool, Any]:
    original = raw
    raw = raw.strip()
    if string and closed and not raw.startswith(("{", "[", '"')):
        return True, original
    try:
        value = _load_json(raw)
        # Decode string-encoded JSON (including its control/comma repair ladder).
        if isinstance(value, str) and value.lstrip().startswith(("{", "[", '"')):
            try:
                value = _load_json(value)
            except ValueError:
                pass
        if string and not raw.startswith(("{", "[", '"')):
            value = original
        return True, value
    except ValueError:
        if string and raw.startswith('"') and raw.endswith('"'):
            # DeepSeek sometimes adds outer quotes without escaping inner JSON.
            try:
                return True, _load_json(raw[1:-1])
            except ValueError:
                pass
        if string and closed:
            return True, original
        # A dangling parameter is only rescued when its JSON is complete.
        return False, None


def _parse_dsml(body: str) -> tuple[list[dict[str, Any]], list[str]]:
    tokens = _tags(body)
    calls: list[dict[str, Any]] = []
    reasons: list[str] = []
    index = 0
    invoked = False
    while index < len(tokens):
        invoke = tokens[index]
        if invoke.name != "invoke" or invoke.closing:
            index += 1
            continue
        invoked = True
        args: dict[str, Any] = {}
        cursor = index + 1
        while cursor < len(tokens):
            token = tokens[cursor]
            if (token.closing and token.name in ("invoke", "calls")) or (not token.closing and token.name == "invoke"):
                break
            if token.name == "parameter" and not token.closing:
                following = cursor + 1
                boundary = tokens[following].start if following < len(tokens) else len(body)
                closed = following < len(tokens) and tokens[following].closing and tokens[following].name == "parameter"
                valid, value = _parameter(body[token.end:boundary], token.attrs.get("string", "false").lower() == "true", closed)
                name = token.attrs.get("name", "")
                if valid and name:
                    if name in ("args", "arguments", "input") and isinstance(value, dict):
                        args.update(value)
                    else:
                        args[name] = value
                cursor = following + 1 if closed else following
            else:
                cursor += 1
        call, reason = _call({"tool": invoke.attrs.get("name"), "id": invoke.attrs.get("id"), "args": args}, dsml=True)
        if call is not None:
            calls.append(call)
        elif reason:
            reasons.append(reason)
        index = max(index + 1, cursor)
    if not invoked:
        reasons.append("dsml-empty")
    return calls, reasons


def parse_tool_calls(text: str, final: bool = True) -> list[dict[str, Any]]:
    """Extract calls, preserving healthy unknown names for executor steering.

    With ``final=False``, incomplete regions and all parser-generated errors are
    deferred. Completed earlier blocks can still be consumed from a stream.
    A final incomplete block may be rescued when its root JSON is complete.
    """
    text = _text(text)
    output: list[dict[str, Any]] = []
    for region in _regions(text):
        if region.kind in ("result", "dsml-closer"):
            continue
        if not final and not region.complete:
            continue
        if region.kind == "fragment":
            calls, reasons = [], ["tool-json-fragment"]
        elif region.kind == "dsml":
            calls, reasons = _parse_dsml(region.body)
        else:
            calls, reasons = _parse_fence(region.body)
        output.extend(calls)
        if final and reasons:
            output.append(_error(reasons))
    return output


def strip_tool_blocks(text: str) -> str:
    """Remove raw calls, results, DSML, and taught fragments, even when invalid.

    Ordinary fenced/inline code and prose are kept verbatim apart from invisible
    bidi marks and the outer whitespace left by removed protocol blocks.
    """
    text = _text(text)
    output: list[str] = []
    position = 0
    for region in _regions(text):
        if region.start < position:
            position = max(position, region.end)
            continue
        output.append(text[position:region.start])
        position = region.end
    output.append(text[position:])
    return "".join(output).strip()


def has_unterminated(text: str) -> bool:
    """Whether an explicit contract region is still open in a live stream.

    DSML container closers implicitly close dangling invokes/parameters. Malformed
    but closed requests must settle and report an error, not wait indefinitely.
    """
    return any(not region.complete for region in _regions(_text(text)))
