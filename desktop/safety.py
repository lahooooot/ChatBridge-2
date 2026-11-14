"""Workspace-confined filesystem operations shared by the UI and tools.

Running an explicitly approved command is not an OS sandbox. All direct file
operations, including paths reached through symlinks, remain inside the root.
"""
from __future__ import annotations

import difflib
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

    # ------------------------------------------------------------------
    # Extended file operations added for the agent tool suite.
    # ------------------------------------------------------------------

    def stat_file(self, path=".") -> dict:
        target = self.resolve(path)
        if not target.exists():
            return {"exists": False, "path": target.relative_to(self.root).as_posix()}
        info = target.stat()
        is_directory = target.is_dir()
        is_symlink = target.is_symlink()
        result = {
            "exists": True,
            "path": target.relative_to(self.root).as_posix(),
            "name": target.name,
            "is_dir": is_directory,
            "is_file": target.is_file(),
            "is_symlink": is_symlink,
            "size": info.st_size,
            "mtime": info.st_mtime,
            "mode": info.st_mode & 0o777,
        }
        if target.is_file():
            try:
                text, size = self._read_text(target)
                result["binary"] = False
                result["line_count"] = len(text.splitlines())
                result["bytes"] = size
            except FileContentError as exc:
                result["binary"] = exc.binary
                result["too_large"] = exc.large
        return result

    def append_file(self, path, content="", create=True) -> dict:
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        with self._lock:
            target = self.resolve(path)
            if target.exists() and not target.is_file():
                raise ValueError("Append target is not a regular file")
            if not target.exists() and not create:
                raise FileNotFoundError(f"File does not exist: {target}")
            parent = self.resolve(target.parent)
            parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8")
            previous = b""
            if target.exists():
                if target.stat().st_size + len(data) > self.max_bytes:
                    raise FileContentError(f"Appended file would exceed the {self.max_bytes}-byte limit", large=True)
                previous = target.read_bytes()
            if _is_binary(previous + data):
                raise FileContentError("Binary content cannot be appended through the text editor", binary=True)
            with target.open("ab") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            size = target.stat().st_size
        return {"appended": True, "bytes": len(data), "total_bytes": size}

    def make_dir(self, path, exist_ok=True) -> dict:
        target = self.resolve(path)
        if target.exists() and not target.is_dir():
            raise ValueError(f"Path already exists and is not a directory: {target}")
        target.mkdir(parents=True, exist_ok=bool(exist_ok))
        return {"created": True, "path": target.relative_to(self.root).as_posix()}

    def delete_file(self, path, recursive=False) -> dict:
        if not isinstance(recursive, bool):
            raise ValueError("recursive must be a boolean")
        target = self.resolve(path)
        if target == self.root:
            raise PermissionError("Refusing to delete the workspace root")
        if not target.exists() and not target.is_symlink():
            raise FileNotFoundError(f"Path does not exist: {target}")
        if target.is_symlink() or target.is_file():
            target.unlink()
            return {"deleted": True, "path": path, "recursive": False}
        if not target.is_dir():
            raise ValueError("Delete target is not a regular file or directory")
        if not recursive:
            try:
                target.rmdir()
            except OSError as exc:
                raise ValueError(f"Directory is not empty; pass recursive=true to remove it: {exc}") from exc
            return {"deleted": True, "path": path, "recursive": False}
        for child in target.rglob("*"):
            self.resolve(child)
        removed = 0
        for child in sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            self.resolve(child)
            if child.is_symlink() or child.is_file():
                child.unlink()
                removed += 1
            elif child.is_dir():
                child.rmdir()
        target.rmdir()
        return {"deleted": True, "path": path, "recursive": True, "removed_entries": removed + 1}

    def rename_file(self, path, new_path) -> dict:
        with self._lock:
            source = self.resolve(path)
            destination = self.resolve(new_path)
            if source == self.root:
                raise PermissionError("Refusing to rename the workspace root")
            if not source.exists() and not source.is_symlink():
                raise FileNotFoundError(f"Source does not exist: {source}")
            if destination.exists():
                raise FileExistsError(f"Destination already exists: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
        return {
            "renamed": True,
            "from": source.relative_to(self.root).as_posix(),
            "to": destination.relative_to(self.root).as_posix(),
        }

    move_file = rename_file

    def copy_file(self, path, new_path, overwrite=False) -> dict:
        if not isinstance(overwrite, bool):
            raise ValueError("overwrite must be a boolean")
        with self._lock:
            source = self.resolve(path)
            destination = self.resolve(new_path)
            if not source.is_file():
                raise ValueError("Copy source must be a regular file")
            if destination.exists() and not overwrite:
                raise FileExistsError(f"Destination already exists: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            if len(data) > self.max_bytes:
                raise FileContentError(f"Source exceeds the {self.max_bytes}-byte limit", large=True)
            destination.write_bytes(data)
        return {
            "copied": True,
            "from": source.relative_to(self.root).as_posix(),
            "to": destination.relative_to(self.root).as_posix(),
            "bytes": len(data),
        }

    def glob(self, pattern, path=".", include_dirs=False, respect_gitignore=True) -> dict:
        if not isinstance(pattern, str) or not pattern or len(pattern) > 512:
            raise ValueError("glob pattern must be a nonempty string of at most 512 characters")
        if not isinstance(include_dirs, bool):
            raise ValueError("include_dirs must be a boolean")
        if not isinstance(respect_gitignore, bool):
            raise ValueError("respect_gitignore must be a boolean")
        target = self.resolve(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Glob base is not a directory: {target}")
        ignored = self._gitignore_patterns(target) if respect_gitignore else ()
        matches, truncated = [], False
        for candidate in target.glob(pattern):
            if len(matches) >= MAX_NODES:
                truncated = True
                break
            try:
                self.resolve(candidate)
            except (PermissionError, ValueError):
                continue
            if candidate.is_symlink():
                continue
            relative = candidate.relative_to(self.root).as_posix()
            if respect_gitignore and self._is_ignored(relative, candidate.is_dir(), ignored):
                continue
            if candidate.is_dir():
                if include_dirs:
                    matches.append({"path": relative, "type": "dir"})
                continue
            if candidate.is_file():
                matches.append({"path": relative, "type": "file", "size": candidate.stat().st_size})
        matches.sort(key=lambda row: row["path"])
        return {"matches": matches, "truncated": truncated}

    def _gitignore_patterns(self, base: Path):
        patterns = []
        for name in (".gitignore",):
            candidate = base / name
            if not candidate.is_file():
                continue
            try:
                text, _ = self._read_text(candidate)
            except (FileContentError, OSError):
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
        return tuple(patterns)

    @staticmethod
    def _is_ignored(relative, is_directory, patterns):
        from fnmatch import fnmatch
        name = relative.rsplit("/", 1)[-1]
        for raw in patterns:
            pattern = raw.lstrip("!")
            negate = raw.startswith("!")
            directory_only = pattern.endswith("/")
            pattern = pattern.rstrip("/")
            if not pattern:
                continue
            matched = (
                fnmatch(relative, pattern)
                or fnmatch(name, pattern)
                or fnmatch(relative, pattern + "/*")
            )
            if directory_only and not is_directory:
                matched = False
            if matched:
                return not negate
        return False

    def grep(self, pattern, path=".", glob=None, case_sensitive=True, fixed_strings=False, context_lines=0, max_matches=100, max_per_file=50) -> dict:
        if not isinstance(pattern, str) or not pattern or len(pattern) > 4096:
            raise ValueError("grep pattern must be a nonempty string of at most 4096 characters")
        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive must be a boolean")
        if not isinstance(fixed_strings, bool):
            raise ValueError("fixed_strings must be a boolean")
        context_lines = _integer(context_lines, "context_lines", 0, 50)
        maximum = _integer(max_matches, "max_matches", 1, 5000)
        maximum_per_file = _integer(max_per_file, "max_per_file", 1, 5000)
        if glob is not None and (not isinstance(glob, str) or len(glob) > 512):
            raise ValueError("glob must be a string of at most 512 characters")
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(re.escape(pattern) if fixed_strings else pattern, flags)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        target = self.resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Grep path does not exist: {target}")
        from fnmatch import fnmatch
        matches, count, total_bytes, skipped, truncated = [], 0, 0, 0, False
        deadline = time.monotonic() + 10

        def files():
            if target.is_file():
                yield target
                return
            for directory, dirs, names in os.walk(target, followlinks=False):
                dirs[:] = sorted(name for name in dirs if name not in NUISANCE_DIRS and not (Path(directory) / name).is_symlink())
                if len(Path(directory).relative_to(target).parts) >= MAX_DEPTH:
                    dirs[:] = []
                for name in sorted(names):
                    candidate = Path(directory) / name
                    if candidate.is_symlink():
                        continue
                    if glob is not None:
                        relative = candidate.relative_to(self.root).as_posix()
                        if not (fnmatch(relative, glob) or fnmatch(candidate.name, glob)):
                            continue
                    yield candidate

        with self._lock:
            for candidate in files():
                if len(matches) >= maximum or count >= MAX_NODES or total_bytes >= 32 * 1024 * 1024 or time.monotonic() >= deadline:
                    truncated = True
                    break
                count += 1
                try:
                    text, size = self._read_text(candidate)
                except (FileContentError, OSError, PermissionError):
                    skipped += 1
                    continue
                total_bytes += size
                lines = text.splitlines()
                file_hits = 0
                for index, line in enumerate(lines):
                    sample = line[:4000]
                    if not compiled.search(sample):
                        continue
                    before = lines[max(0, index - context_lines):index]
                    after = lines[index + 1:index + 1 + context_lines]
                    matches.append({
                        "file": candidate.relative_to(self.root).as_posix(),
                        "line": index + 1,
                        "text": line[:2000],
                        "before": before,
                        "after": after,
                    })
                    file_hits += 1
                    if len(matches) >= maximum or file_hits >= maximum_per_file:
                        break
                if file_hits >= maximum_per_file:
                    truncated = True
        return {"matches": matches, "truncated": truncated, "skipped": skipped}

    def edit_file(self, path, search, replace, count=1, regex=False) -> dict:
        if not isinstance(search, str) or not search:
            raise ValueError("search must be a nonempty string")
        if not isinstance(replace, str):
            raise ValueError("replace must be a string")
        if not isinstance(regex, bool):
            raise ValueError("regex must be a boolean")
        if count != "all" and (type(count) is not int or count < 1):
            raise ValueError("count must be a positive integer or the string 'all'")
        with self._lock:
            target = self.resolve(path)
            original, _ = self._read_text(target)
            if regex:
                try:
                    compiled = re.compile(search)
                except re.error as exc:
                    raise ValueError(f"Invalid regular expression: {exc}") from exc
                total = len(compiled.findall(original))
                if total == 0:
                    raise ValueError("edit_file search matched zero occurrences")
                if count != "all" and total != count:
                    raise ValueError(f"edit_file expected {count} match(es) but found {total}")
                limit = 0 if count == "all" else count
                updated = compiled.sub(replace, original, count=limit)
            else:
                total = original.count(search)
                if total == 0:
                    raise ValueError("edit_file search matched zero occurrences")
                if count != "all" and total != count:
                    raise ValueError(f"edit_file expected {count} match(es) but found {total}")
                limit = -1 if count == "all" else count
                updated = original.replace(search, replace, limit)
            data = updated.encode("utf-8")
            if len(data) > self.max_bytes:
                raise FileContentError(f"Content exceeds the {self.max_bytes}-byte limit", large=True)
            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=path, tofile=path, n=2,
            ))[:20000]
        return {"edited": True, "matches": total, "bytes": len(data), "diff": diff}

    def diff_preview(self, path, content=None, search=None, replace=None) -> dict:
        target = self.resolve(path)
        try:
            original, _ = self._read_text(target)
            exists = True
        except FileNotFoundError:
            original, exists = "", False
        if content is not None:
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            updated = content
        else:
            if not isinstance(search, str) or not search or not isinstance(replace, str):
                raise ValueError("diff_preview needs content or both search and replace")
            matches = original.count(search)
            if matches == 0:
                raise ValueError("diff_preview search matched zero occurrences")
            updated = original.replace(search, replace, 1)
        import difflib as _difflib
        diff = "".join(_difflib.unified_diff(
            original.splitlines(keepends=True), updated.splitlines(keepends=True),
            fromfile=path if exists else "/dev/null", tofile=path, n=3,
        ))[:40000]
        return {"diff": diff, "exists": exists, "bytes_before": len(original.encode()), "bytes_after": len(updated.encode())}

    def read_multiple_files(self, paths, limit=400, max_total_bytes=200_000) -> dict:
        if not isinstance(paths, list) or not paths or not all(isinstance(item, str) and item for item in paths):
            raise ValueError("paths must be a nonempty list of path strings")
        limit = _integer(limit, "limit", 1, 100_000)
        max_total_bytes = _integer(max_total_bytes, "max_total_bytes", 1, 4 * 1024 * 1024)
        results, total = [], 0
        for entry in paths:
            try:
                payload = self.read_file(entry, offset=0, limit=limit)
            except Exception as exc:
                results.append({"path": entry, "ok": False, "error": str(exc)})
                continue
            total += payload["bytes"]
            results.append({"path": entry, "ok": True, **payload})
            if total >= max_total_bytes:
                break
        return {"files": results, "total_bytes": total}

    def tail_file(self, path, lines=100) -> dict:
        lines = _integer(lines, "lines", 1, 10_000)
        target = self.resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"File does not exist: {target}")
        size = target.stat().st_size
        chunk = min(size, 256 * 1024)
        with target.open("rb") as stream:
            stream.seek(-chunk, os.SEEK_END)
            data = stream.read(chunk)
        if _is_binary(data):
            raise FileContentError("Binary file cannot be opened as text", binary=True)
        text = data.decode("utf-8", errors="replace")
        selected = text.splitlines()[-lines:]
        return {
            "content": "\n".join(selected),
            "lines": len(selected),
            "bytes": size,
            "truncated": size > chunk,
        }

    def outline(self, path) -> dict:
        target = self.resolve(path)
        text, _ = self._read_text(target)
        suffix = target.suffix.lower()
        symbols = []
        if suffix == ".py":
            import ast
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                raise ValueError(f"Cannot parse Python source: {exc}") from exc
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.append({
                        "name": node.name,
                        "kind": type(node).__name__,
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                    })
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target_node in targets:
                        if isinstance(target_node, ast.Name):
                            symbols.append({"name": target_node.id, "kind": "Variable", "line": node.lineno, "end_line": node.lineno})
        else:
            patterns = (
                (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"), "Function"),
                (re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"), "Class"),
                (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*="), "Variable"),
                (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)"), "Function"),
                (re.compile(r"^\s*(?:pub\s+)?(?:fn|struct|enum|trait|impl)\s+(\w+)"), "Symbol"),
            )
            for index, line in enumerate(text.splitlines(), 1):
                for compiled, kind in patterns:
                    match = compiled.match(line)
                    if match:
                        symbols.append({"name": match.group(1), "kind": kind, "line": index, "end_line": index})
                        break
        return {"path": target.relative_to(self.root).as_posix(), "symbols": symbols, "truncated": len(symbols) >= 2000}

    def find_symbol(self, name, path=".", kind=None, max=100) -> dict:
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a nonempty string")
        maximum = _integer(max, "max", 1, 1000)
        target = self.resolve(path)
        results = []
        for directory, dirs, names in os.walk(target, followlinks=False):
            dirs[:] = sorted(item for item in dirs if item not in NUISANCE_DIRS and not (Path(directory) / item).is_symlink())
            for filename in sorted(names):
                candidate = Path(directory) / filename
                if candidate.suffix.lower() not in (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cs", ".rb"):
                    continue
                try:
                    text, _ = self._read_text(candidate)
                except (FileContentError, OSError, PermissionError):
                    continue
                for index, line in enumerate(text.splitlines(), 1):
                    for compiled, item_kind in (
                        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|def|class|interface|type|struct|enum|trait)\s+" + re.escape(name) + r"\b"), "definition"),
                        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+" + re.escape(name) + r"\b"), "binding"),
                    ):
                        if compiled.match(line):
                            if kind and kind != item_kind:
                                break
                            results.append({"file": candidate.relative_to(self.root).as_posix(), "line": index, "kind": item_kind, "text": line[:400]})
                            break
                if len(results) >= maximum:
                    return {"symbols": results, "truncated": True}
        return {"symbols": results, "truncated": False}
