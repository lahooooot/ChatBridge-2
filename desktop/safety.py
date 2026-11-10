"""Workspace-confined filesystem operations shared by the UI and tools.

Running an explicitly approved command is not an OS sandbox. All direct file
operations, including paths reached through symlinks, remain inside the root.
"""
from __future__ import annotations

import itertools
import os
import re
import tempfile
import threading
import time
from pathlib import Path, PureWindowsPath

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 8
MAX_NODES = 5000
NUISANCE_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", "dist", "build", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".cache",
    ".tox", ".idea", "target", ".chatbridge",
})
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class FileContentError(ValueError):
    def __init__(self, message, *, binary=False, large=False):
        super().__init__(message)
        self.binary = binary
        self.large = large


def _integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")
    return value


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    sample = data[:8192]
    controls = sum(byte < 32 and byte not in (9, 10, 12, 13) for byte in sample)
    return bool(sample) and controls / len(sample) > 0.03


class Workspace:
    def __init__(self, root, max_bytes=MAX_FILE_BYTES):
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError(f"Workspace is not a directory: {self.root}")
        self.max_bytes = _integer(max_bytes, "max_bytes", 1, 64 * 1024 * 1024)
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.root)), threading.RLock())

    def resolve(self, path) -> Path:
        if not isinstance(path, (str, os.PathLike)):
            raise ValueError("Path must be a string or path-like value")
        raw = os.fspath(path)
        if not isinstance(raw, str) or "\x00" in raw or len(raw) > 32768:
            raise ValueError("Path contains invalid characters or is too long")
        if os.name != "nt" and (PureWindowsPath(raw).drive or raw.startswith("\\\\")):
            raise PermissionError("Windows absolute paths cannot be used in this workspace")
        candidate = Path(raw or ".").expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            resolved = candidate.resolve()
        except (RuntimeError, OSError) as exc:
            raise ValueError(f"Cannot resolve path: {raw}: {exc}") from exc
        if not resolved.is_relative_to(self.root):
            raise PermissionError(f"Path is outside the workspace: {raw}")
        return resolved

    def _read_text(self, target: Path) -> tuple[str, int]:
        target = self.resolve(target)
        if not target.is_file():
            if not target.exists():
                raise FileNotFoundError(f"File does not exist: {target}")
            raise ValueError(f"Path is not a regular file: {target}")
        if target.stat().st_size > self.max_bytes:
            raise FileContentError(f"File exceeds the {self.max_bytes}-byte text limit", large=True)
        with target.open("rb") as stream:
            data = stream.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise FileContentError(f"File exceeds the {self.max_bytes}-byte text limit", large=True)
        if _is_binary(data):
            raise FileContentError("Binary file cannot be opened as text", binary=True)
        try:
            return data.decode("utf-8"), len(data)
        except UnicodeDecodeError as exc:
            raise FileContentError("File is binary or is not UTF-8 text", binary=True) from exc

    def read_file(self, path, offset=0, limit=2000) -> dict:
        offset = _integer(offset, "offset", 0, 10_000_000)
        if limit is not None:
            limit = _integer(limit, "limit", 1, 100_000)
        with self._lock:
            text, size = self._read_text(self.resolve(path))
        lines = text.splitlines(keepends=True)
        selected = lines[offset:] if limit is None else lines[offset:offset + limit]
        return {
            "content": "".join(selected), "lines": len(selected), "bytes": size,
            "total_lines": len(lines), "truncated": offset > 0 or offset + len(selected) < len(lines),
        }

    def write_file(self, path, content=None, search=None, replace=None) -> dict:
        if content is not None and (search is not None or replace is not None):
            raise ValueError("Use either content or search and replace, not both")
        if content is None and (not isinstance(search, str) or not isinstance(replace, str)):
            raise ValueError("write_file needs content or both search and replace strings")
        if content is not None and not isinstance(content, str):
            raise ValueError("File content must be a string")
        with self._lock:
            target = self.resolve(path)
            if content is None:
                if not search:
                    raise ValueError("Patch search cannot be empty")
                original, _ = self._read_text(target)
                # Count overlapping matches as well: 'aa' in 'aaa' is ambiguous.
                first = original.find(search)
                second = original.find(search, first + 1) if first >= 0 else -1
                matches = 0 if first < 0 else 2 if second >= 0 else 1
                if matches != 1:
                    raise ValueError(f"Patch search must match exactly once; found {matches} matches")
                content = original.replace(search, replace, 1)
            data = content.encode("utf-8")
            if len(data) > self.max_bytes:
                raise FileContentError(f"Content exceeds the {self.max_bytes}-byte limit", large=True)
            if _is_binary(data):
                raise FileContentError("Binary content cannot be saved through the text editor", binary=True)
            if target.exists() and not target.is_file():
                raise ValueError("Write target is not a regular file")
            parent = self.resolve(target.parent)
            parent.mkdir(parents=True, exist_ok=True)
            parent = self.resolve(parent)
            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if target.exists():
                    os.chmod(temporary, target.stat().st_mode & 0o777)
                # Check again after directory creation and before replacement.
                if self.resolve(target) != target or self.resolve(parent) != parent:
                    raise PermissionError("File path changed while saving")
                os.replace(temporary, target)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return {"written": True, "lines": len(content.splitlines()), "bytes": len(data)}

    def list_dir(self, path=".", depth=1) -> dict:
        depth = _integer(depth, "depth", 1, MAX_DEPTH)
        target = self.resolve(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {target}")
        entries, truncated = [], False

        def walk(directory, level):
            nonlocal truncated
            with os.scandir(directory) as iterator:
                remaining = MAX_NODES - len(entries)
                children = list(itertools.islice(iterator, remaining + 1))
                if len(children) > remaining:
                    truncated = True
                    children = children[:remaining]
                children.sort(key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.casefold()))
            for child in children:
                if len(entries) >= MAX_NODES:
                    truncated = True
                    return
                child_path = Path(child.path)
                symbolic = child.is_symlink()
                blocked = False
                try:
                    self.resolve(child_path)
                except (PermissionError, ValueError):
                    blocked = True
                is_directory = child.is_dir(follow_symlinks=False)
                row = {
                    "name": child_path.relative_to(target).as_posix(),
                    "path": child_path.relative_to(self.root).as_posix(),
                    "type": "symlink" if symbolic else "dir" if is_directory else "file",
                    "hidden": child.name.startswith(".") or child.name in NUISANCE_DIRS,
                }
                if blocked:
                    row["blocked"] = True
                if not is_directory and not symbolic:
                    row["size"] = child.stat(follow_symlinks=False).st_size
                entries.append(row)
                if is_directory and level < depth and child.name not in NUISANCE_DIRS and not blocked:
                    walk(child_path, level + 1)

        with self._lock:
            walk(target, 1)
        return {"entries": entries, "truncated": truncated}

    def search_files(self, query, path=".", regex=False, max=50) -> dict:
        if not isinstance(query, str) or not query or len(query) > 512:
            raise ValueError("Search query must be a nonempty string of at most 512 characters")
        if not isinstance(regex, bool):
            raise ValueError("regex must be a boolean")
        maximum = _integer(max, "max", 1, 1000)
        try:
            pattern = re.compile(query) if regex else None
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        # Avoid the common exponential nested-repeat patterns in user regexes.
        if regex and re.search(r"\([^)]*[*+][^)]*\)[*+{]", query):
            raise ValueError("Nested repetition is not supported in file-search regular expressions")
        target = self.resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Search path does not exist: {target}")
        matches, count, total_bytes, skipped, truncated = [], 0, 0, 0, False
        deadline = time.monotonic() + 5

        def files():
            if target.is_file():
                yield target
                return
            for directory, dirs, names in os.walk(target, followlinks=False):
                dirs[:] = sorted(name for name in dirs if name not in NUISANCE_DIRS and not (Path(directory) / name).is_symlink())
                relative_depth = len(Path(directory).relative_to(target).parts)
                if relative_depth >= MAX_DEPTH:
                    dirs[:] = []
                for name in sorted(names):
                    candidate = Path(directory) / name
                    if not candidate.is_symlink():
                        yield candidate

        with self._lock:
            for candidate in files():
                if count >= MAX_NODES or total_bytes >= 32 * 1024 * 1024 or time.monotonic() >= deadline:
                    truncated = True
                    break
                count += 1
                try:
                    text, size = self._read_text(candidate)
                except (FileContentError, OSError, PermissionError):
                    skipped += 1
                    continue
                total_bytes += size
                for line_number, line in enumerate(text.splitlines(), 1):
                    sample = line[:4000]
                    if pattern.search(sample) if pattern is not None else query in line:
                        matches.append({"file": candidate.relative_to(self.root).as_posix(), "line": line_number, "text": line[:2000]})
                        if len(matches) >= maximum:
                            return {"matches": matches, "truncated": True, "skipped": skipped}
        return {"matches": matches, "truncated": truncated, "skipped": skipped}
