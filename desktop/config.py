"""Atomic, thread-safe configuration and user-owned agent rules."""
from __future__ import annotations

import copy
import json
import os
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Any

RULES_VERSION = "2.60.0"
DATA_DIR_NAME = f".chatbridge-{RULES_VERSION}"


def default_data_dir() -> Path:
    """Return the versioned per-user data directory used by the packaged app."""
    return Path.home() / DATA_DIR_NAME
DEFAULT_RULES = [
    {"id": "agent-md", "text": "I want you, whenever a project or workspace is attached, to first search for an agent.md file at the workspace root. If agent.md exists, I want its contents treated as part of our working contract and followed for the rest of the session. If agent.md does not exist, I want you to create it and record in it every rule or convention you settle on during the session so future sessions inherit them.", "enabled": True, "builtin": True},
    {"id": "local-tools", "text": "I have a local bridge to my working folder with read_file, write_file, list_dir, search_files, run_command, edit_file, stat_file, append_file, make_dir, delete_file, rename_file, move_file, copy_file, glob, grep, diff_preview, read_multiple_files, tail_file, outline, find_symbol, git_status, git_diff, git_log, git_show, git_blame, git_stage, git_unstage, git_commit, git_branch, git_checkout, snapshot, rollback, process_control, run_tests and http_fetch available. I would like you to use these tools when they help with my request.", "enabled": True, "builtin": True},
    {"id": "tool-format", "text": 'I can run tool requests written as a JSON object in a chatbridge-tool-call code fence, for example:\n```chatbridge-tool-call\n{"tool":"read_file","args":{"path":"src/app.py"}}\n```\nI can also handle several separate requests in one reply.', "enabled": True, "builtin": True},
    {"id": "edit-format", "text": "I prefer edit_file with path, search and replace for local edits; it must match the search text exactly count times (default 1). I will use write_file only when you mean to replace or create the whole file.", "enabled": True, "builtin": True},
    {"id": "read-format", "text": "I understand that read_file accepts optional offset and limit for large files; use tail_file for logs, outline for a symbol summary and find_symbol to locate a definition before editing.", "enabled": True, "builtin": True},
    {"id": "workspace", "text": "I use paths relative to my working folder. I would like you to inspect the relevant files before changing them, and keep changes focused on what I asked for.", "enabled": True, "builtin": True},
    {"id": "write-format", "text": "I can save a file with write_file using path and content, or edit it using path, search and replace. I need the search text to occur exactly once so the edit is unambiguous.", "enabled": True, "builtin": True},
    {"id": "tool-results", "text": "I will send back the real tool results after each request. I would like you to wait for those results, explain any errors honestly, and then continue until you can give me a final answer.", "enabled": True, "builtin": True},
]
BUILTIN_RULES = DEFAULT_RULES
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def atomic_json_write(path: Path, value: Any) -> None:
    """Write complete UTF-8 JSON, fsync it, then atomically replace the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _read_object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _defaults() -> dict:
    return {
        "ws_port": 8787, "full_access": True, "approval_timeout": 120,
        "provider_enabled": False, "provider_port": 8788,
        "provider_timeout": 600, "provider_key": secrets.token_urlsafe(32),
        "updates_seen": False, "custom_models": [],
        "agent_rules_on": True, "agent_rules": copy.deepcopy(DEFAULT_RULES),
        "agent_rules_version": RULES_VERSION,
        "agent_rules_defaults": {rule["id"]: rule["text"] for rule in DEFAULT_RULES},
        "language": "en", "theme": "dark", "font_size": 14,
    }


def _validate_rules(rules: Any) -> list[dict]:
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("Agent rules must be a list of at most 100 rows")
    result, seen = [], set()
    for row in rules:
        if not isinstance(row, dict):
            raise ValueError("Every agent rule must be an object")
        ident, text = row.get("id"), row.get("text")
        if not isinstance(ident, str) or not ident or len(ident) > 128 or ident in seen:
            raise ValueError("Agent rule IDs must be nonempty and unique")
        if not isinstance(text, str) or len(text) > 16000:
            raise ValueError("Agent rule text must be a string of at most 16000 characters")
        if not isinstance(row.get("enabled", True), bool) or not isinstance(row.get("builtin", False), bool):
            raise ValueError("Rule enabled and builtin fields must be booleans")
        seen.add(ident)
        result.append({"id": ident, "text": text, "enabled": row.get("enabled", True), "builtin": row.get("builtin", False)})
    return result


def _migrate_custom_models(value: Any) -> tuple[list[dict], bool]:
    """Normalize legacy UI model rows without making startup fail.

    Early preview builds used ``url``/``title`` and sometimes wrote a partial
    row while the add-model form was being edited.  Config loaded from disk is
    user data, so a stale row must not make the desktop app unlaunchable.  We
    preserve complete rows, repair obvious aliases, and drop rows that cannot
    identify a usable HTTP home.  New writes still go through strict
    ``_validate`` below.
    """
    if not isinstance(value, list):
        return [], True
    result, changed, seen = [], False, set()
    for raw in value:
        if not isinstance(raw, dict):
            changed = True
            continue
        row = dict(raw)
        ident = row.get("id")
        name = row.get("name") or row.get("title")
        home = row.get("home") or row.get("url")
        if not isinstance(ident, str) or not ident.strip():
            # Do not invent an identity for a row without a usable name/home;
            # for recognizable legacy rows a stable slug is sufficient.
            seed = name if isinstance(name, str) else ""
            ident = "c_" + "".join(ch.lower() if ch.isalnum() else "_" for ch in seed).strip("_")
            if ident == "c_":
                changed = True
                continue
            suffix, candidate = 2, ident
            while candidate in seen:
                candidate, suffix = f"{ident}_{suffix}", suffix + 1
            ident = candidate
        if not all(isinstance(item, str) and item.strip() for item in (name, home)):
            changed = True
            continue
        if not str(home).strip().startswith(("https://", "http://")) or ident in seen:
            changed = True
            continue
        normalized = {"id": ident.strip(), "name": name.strip(), "home": home.strip()}
        if row != normalized:
            changed = True
        seen.add(ident)
        result.append(normalized)
    return result, changed


class ConfigStore:
    def __init__(self, base=None):
        self.base = Path(base).expanduser().resolve() if base is not None else default_data_dir()
        self.path = self.base / "config.json"
        self.state_path = self.base / "ui_state.json"
        self._lock = _path_lock(self.base)
        with self._lock:
            existing = _read_object(self.path)
            config = _defaults()
            config.update(existing)
            # Retired connection modes are not part of this architecture.
            config.pop("browser_mode", None)
            custom_models, models_changed = _migrate_custom_models(config.get("custom_models"))
            config["custom_models"] = custom_models
            if not isinstance(config.get("provider_key"), str) or not config["provider_key"].strip():
                config["provider_key"] = secrets.token_urlsafe(32)
            baseline = existing.get("agent_rules_defaults", {})
            if not isinstance(baseline, dict):
                baseline = {}
            current = {rule["id"]: rule["text"] for rule in DEFAULT_RULES}
            rows = _validate_rules(config["agent_rules"])
            for row in rows:
                # Never guess whether unfamiliar text is user-edited. Snapshots
                # let subsequent releases recognize untouched builtins exactly.
                if row["builtin"] and row["id"] in current and row["text"] == baseline.get(row["id"]):
                    row["text"] = current[row["id"]]
            config["agent_rules"] = rows
            config["agent_rules_defaults"] = current
            config["agent_rules_version"] = RULES_VERSION
            self._validate(config)
            if config != existing or models_changed:
                atomic_json_write(self.path, config)

    @staticmethod
    def _validate(config: dict) -> None:
        for key in ("ws_port", "provider_port"):
            if type(config.get(key)) is not int or not 1 <= config[key] <= 65535:
                raise ValueError(f"{key} must be an integer between 1 and 65535")
        for key in ("approval_timeout", "provider_timeout"):
            if type(config.get(key)) is not int or not 1 <= config[key] <= 86400:
                raise ValueError(f"{key} must be an integer between 1 and 86400")
        for key in ("full_access", "provider_enabled", "updates_seen", "agent_rules_on"):
            if not isinstance(config.get(key), bool):
                raise ValueError(f"{key} must be a boolean")
        if not isinstance(config.get("provider_key"), str) or not config["provider_key"].strip():
            raise ValueError("provider_key must be a nonempty string")
        if not isinstance(config.get("custom_models"), list):
            raise ValueError("custom_models must be a list")
        seen = set()
        for model in config["custom_models"]:
            if not isinstance(model, dict) or not all(isinstance(model.get(key), str) and model[key].strip() for key in ("id", "name", "home")):
                raise ValueError("Each custom model needs id, name and home strings")
            if model["id"] in seen or not model["home"].startswith(("https://", "http://")):
                raise ValueError("Custom model IDs must be unique and home must be an HTTP URL")
            seen.add(model["id"])
        _validate_rules(config["agent_rules"])

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(_read_object(self.path))

    def update(self, patch) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("Configuration patch must be an object")
        if "browser_mode" in patch:
            raise ValueError("browser_mode is no longer supported")
        if any(key in patch for key in ("agent_rules_defaults", "agent_rules_version")):
            raise ValueError("Agent rule upgrade metadata cannot be edited")
        with self._lock:
            config = _read_object(self.path)
            config.update(copy.deepcopy(patch))
            if "agent_rules" in patch:
                config["agent_rules"] = _validate_rules(patch["agent_rules"])
            self._validate(config)
            atomic_json_write(self.path, config)
            return copy.deepcopy(config)

    def rules_get(self) -> dict:
        config = self.get()
        return {"rules": config["agent_rules"], "on": config["agent_rules_on"]}

    def rules_set(self, rules, on=True) -> dict:
        self.update({"agent_rules": _validate_rules(rules), "agent_rules_on": on})
        return self.rules_get()

    def rules_reset(self) -> dict:
        return self.rules_set(copy.deepcopy(DEFAULT_RULES), True)

    def rules_preview(self, text="", workspace=None) -> str:
        if not isinstance(text, str):
            raise ValueError("Message text must be a string")
        settings = self.rules_get()
        if not workspace or not settings["on"]:
            return text
        rules = [row["text"].strip() for row in settings["rules"] if row["enabled"] and row["text"].strip()]
        if not rules:
            return text
        root = getattr(workspace, "root", workspace)
        context = f"My working folder is {json.dumps(str(root), ensure_ascii=False)}."
        return "\n\n".join(part for part in [text, context, *rules] if part)

    def load_state(self) -> dict:
        with self._lock:
            return copy.deepcopy(_read_object(self.state_path))

    def save_state(self, state) -> None:
        if not isinstance(state, dict):
            raise ValueError("UI state must be an object")
        snapshot = copy.deepcopy(state)
        with self._lock:
            atomic_json_write(self.state_path, snapshot)
