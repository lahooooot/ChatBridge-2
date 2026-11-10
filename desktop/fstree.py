"""Bounded project file tree and text editor operations."""
from __future__ import annotations

import itertools
import os
from pathlib import Path

from .safety import FileContentError, MAX_FILE_BYTES, NUISANCE_DIRS, Workspace, _integer


class FileTree:
    def __init__(self, root, max_bytes=MAX_FILE_BYTES, max_depth=5, max_nodes=2000):
        self.workspace = Workspace(root, max_bytes=max_bytes)
        self.root = self.workspace.root
        self.max_depth = _integer(max_depth, "max_depth", 1, 16)
        self.max_nodes = _integer(max_nodes, "max_nodes", 1, 100_000)

    def tree(self, path="") -> dict:
        target = self.workspace.resolve(path or ".")
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {target}")
        count, truncated = 0, False

        def children(directory: Path, level: int) -> list:
            nonlocal count, truncated
            remaining = self.max_nodes - count
            if remaining <= 0:
                truncated = True
                return []
            with os.scandir(directory) as iterator:
                # Bound enumeration as well as returned nodes; never sort a
                # million entries simply to show a two-thousand-node tree.
                batch = list(itertools.islice(iterator, remaining + 1))
            if len(batch) > remaining:
                truncated = True
                batch = batch[:remaining]
            batch.sort(key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.casefold()))
            rows = []
            for entry in batch:
                if count >= self.max_nodes:
                    truncated = True
                    break
                count += 1
                candidate = Path(entry.path)
                symbolic = entry.is_symlink()
                directory_entry = entry.is_dir(follow_symlinks=False)
                hidden = entry.name.startswith(".") or entry.name in NUISANCE_DIRS
                row = {
                    "name": entry.name, "path": candidate.relative_to(self.root).as_posix(),
                    "type": "symlink" if symbolic else "dir" if directory_entry else "file",
                    "size": 0, "children": [], "hidden": hidden,
                }
                try:
                    self.workspace.resolve(candidate)
                    if not symbolic and not directory_entry:
                        row["size"] = entry.stat(follow_symlinks=False).st_size
                    if directory_entry:
                        if entry.name in NUISANCE_DIRS:
                            row["collapsed"] = True
                        elif level >= self.max_depth:
                            row["collapsed"] = True
                            row["depth_limited"] = True
                            truncated = True
                        else:
                            row["children"] = children(candidate, level + 1)
                except (PermissionError, ValueError) as exc:
                    row.update({"blocked": True, "error": str(exc)})
                except OSError as exc:
                    row["error"] = str(exc)
                rows.append(row)
            return rows

        with self.workspace._lock:
            entries = children(target, 1)
        return {"ok": True, "entries": entries, "root": str(self.root), "path": str(target), "truncated": truncated}

    def read(self, path) -> dict:
        target = self.workspace.resolve(path)
        try:
            result = self.workspace.read_file(target, limit=None)
        except FileContentError as exc:
            return {"ok": False, "path": str(target), "error": str(exc), "binary": exc.binary, "large": exc.large}
        return {"ok": True, "path": str(target), **result}

    def write(self, path, content) -> dict:
        target = self.workspace.resolve(path)
        result = self.workspace.write_file(target, content=content)
        return {"ok": True, "path": str(target), **result}
