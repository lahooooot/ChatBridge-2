"""Per-site selector hints, stored in a standalone shareable file.

Keyed by hostname (not by custom-model id) so a hints file can be handed to
another user whose model row has a different generated id.  The file lives
next to config.json and is safe to copy/replace independently.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

HINTS_FILE = "platform_hints.json"
VERSION = 1
# Only these keys are meaningful to agent_cb.js.  Everything else is dropped
# so a hand-edited or third-party file cannot inject arbitrary fields.
SELECTOR_KEYS = ("editor", "send", "stop", "unit", "users", "body", "transcript", "loading")
MAX_SELECTORS = 12
MAX_SELECTOR_LEN = 300
MAX_OBSERVATIONS = 5

_lock = threading.RLock()


def host_of(url: str) -> str:
    try:
        return (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return ""


def _clean_selectors(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text and len(text) <= MAX_SELECTOR_LEN and text not in out:
                out.append(text)
        if len(out) >= MAX_SELECTORS:
            break
    return out


def clean_hints(value) -> dict:
    """Keep only known selector arrays; never pass arbitrary objects through."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in SELECTOR_KEYS:
        selectors = _clean_selectors(value.get(key))
        if selectors:
            result[key] = selectors
    return result


def _path(base) -> Path:
    return Path(base) / HINTS_FILE


def load(base) -> dict:
    path = _path(base)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    hosts = raw.get("hosts") if isinstance(raw, dict) else None
    return hosts if isinstance(hosts, dict) else {}


def _save(base, hosts: dict) -> None:
    path = _path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": VERSION, "updated": int(time.time()), "hosts": hosts}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def for_host(base, host: str) -> dict:
    """Return usable selectors for a hostname, or {} when nothing is known."""
    host = (host or "").lower()
    if not host:
        return {}
    with _lock:
        row = load(base).get(host)
    if not isinstance(row, dict):
        return {}
    return clean_hints(row.get("hints"))


def get(base, host: str) -> dict:
    host = (host or "").lower()
    with _lock:
        row = load(base).get(host)
    if not isinstance(row, dict):
        return {"host": host, "hints": {}, "observed": []}
    return {"host": host, "hints": clean_hints(row.get("hints")),
            "source": row.get("source", "manual"), "observed": row.get("observed", [])[-MAX_OBSERVATIONS:]}


def set_host(base, host: str, hints) -> dict:
    host = (host or "").lower()
    if not host or "." not in host:
        raise ValueError("A hostname such as chat.example.com is required")
    cleaned = clean_hints(hints)
    with _lock:
        hosts = load(base)
        row = hosts.get(host) if isinstance(hosts.get(host), dict) else {}
        if cleaned:
            row["hints"] = cleaned
            row["source"] = "manual"
            row["updated"] = int(time.time())
            hosts[host] = row
        else:
            hosts.pop(host, None)
        _save(base, hosts)
    return get(base, host)


def record_observation(base, host: str, reason: str, observed) -> bool:
    """Remember what the page looked like when automation failed.

    Stored for the user to review/accept; never applied automatically, because
    guessing a response container wrong is worse than reporting nothing.
    """
    host = (host or "").lower()
    if not host or not isinstance(observed, dict):
        return False
    entry = {
        "at": int(time.time()),
        "reason": str(reason or "unknown")[:40],
        "editors": _clean_selectors(observed.get("editors")),
        "sends": [row for row in (observed.get("sends") or []) if isinstance(row, dict)][:8],
    }
    if not entry["editors"] and not entry["sends"]:
        return False
    with _lock:
        hosts = load(base)
        row = hosts.get(host) if isinstance(hosts.get(host), dict) else {}
        observed_list = row.get("observed") if isinstance(row.get("observed"), list) else []
        # Skip an identical failure to keep the file small and readable.
        for previous in observed_list[-2:]:
            if previous.get("editors") == entry["editors"] and previous.get("reason") == entry["reason"]:
                return False
        observed_list.append(entry)
        row["observed"] = observed_list[-MAX_OBSERVATIONS:]
        hosts[host] = row
        _save(base, hosts)
    return True


def suggest(base, host: str) -> dict:
    """Turn the latest observation into an editable draft for the UI."""
    row = get(base, host)
    hints = dict(row.get("hints") or {})
    observed = row.get("observed") or []
    if observed:
        last = observed[-1]
        if not hints.get("editor") and last.get("editors"):
            hints["editor"] = last["editors"][:4]
        if not hints.get("send") and last.get("sends"):
            best = [row2.get("path") for row2 in last["sends"] if row2.get("path") and row2.get("score", 0) > 0]
            if best:
                hints["send"] = best[:4]
    return {"host": host, "hints": hints, "observed": observed}
