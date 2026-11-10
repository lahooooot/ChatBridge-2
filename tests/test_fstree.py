import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from desktop.fstree import FileTree


def flatten(rows):
    for row in rows:
        yield row
        yield from flatten(row["children"])


def test_tree_shape_and_collapsed_nuisance_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n")
    (tmp_path / "README.md").write_text("hello\n")
    for name in (".git", "node_modules", "__pycache__", "dist"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "hidden.txt").write_text("hidden")
    tree = FileTree(tmp_path).tree()
    assert tree["ok"] and tree["root"] == str(tmp_path)
    nodes = list(flatten(tree["entries"]))
    assert all(set(("name", "path", "type", "size", "children", "hidden")) <= set(row) for row in nodes)
    assert any(row["path"] == "src/app.py" and row["type"] == "file" for row in nodes)
    for name in (".git", "node_modules", "__pycache__", "dist"):
        row = next(row for row in nodes if row["name"] == name)
        assert row["hidden"] and row["collapsed"] and not row["children"]


def test_node_and_depth_budgets(tmp_path):
    current = tmp_path
    for index in range(10):
        current = current / f"d{index}"
        current.mkdir()
        (current / "file.txt").write_text("a")
    tree = FileTree(tmp_path, max_depth=2, max_nodes=3).tree()
    assert len(list(flatten(tree["entries"]))) <= 3
    assert tree["truncated"] is True
    assert not any(row["path"].count("/") >= 2 for row in flatten(tree["entries"]))
    for index in range(40):
        (tmp_path / f"flat{index}.txt").write_text("x")
    capped = FileTree(tmp_path, max_nodes=7).tree()
    assert len(list(flatten(capped["entries"]))) <= 7
    assert capped["truncated"]


def test_read_write_utf8_line_and_byte_metadata(tmp_path):
    tree = FileTree(tmp_path)
    content = "hello\nسلام\n"
    saved = tree.write("src/new.txt", content)
    assert saved["ok"] and saved["written"]
    assert saved["lines"] == 2 and saved["bytes"] == len(content.encode())
    read = tree.read("src/new.txt")
    assert read["ok"] and read["content"] == content
    assert read["path"] == str(tmp_path / "src" / "new.txt")
    assert read["bytes"] == saved["bytes"]
    assert tree.tree("src")["entries"][0]["path"] == "src/new.txt"


@pytest.mark.parametrize("data,binary,large", [(b"abc\x00def", True, False), (b"\xff\xfe", True, False), (b"a" * 33, False, True)])
def test_binary_and_large_are_truthful_read_cards(tmp_path, data, binary, large):
    (tmp_path / "file.dat").write_bytes(data)
    result = FileTree(tmp_path, max_bytes=32).read("file.dat")
    assert result["ok"] is False
    assert result["binary"] is binary and result["large"] is large
    assert result["error"]


def test_default_cap_is_two_megabytes_and_write_cap_is_enforced(tmp_path):
    tree = FileTree(tmp_path)
    assert tree.workspace.max_bytes == 2 * 1024 * 1024
    (tmp_path / "large.txt").write_bytes(b"a" * (tree.workspace.max_bytes + 1))
    assert tree.read("large.txt")["large"]
    with pytest.raises(ValueError, match="limit"):
        FileTree(tmp_path, max_bytes=4).write("new.txt", "12345")
    assert not (tmp_path / "new.txt").exists()


@pytest.mark.parametrize("operation", ["read", "write", "tree"])
def test_outside_workspace_is_rejected(tmp_path, operation):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    tree = FileTree(root)
    with pytest.raises(PermissionError):
        getattr(tree, operation)("../outside.txt", "changed") if operation == "write" else getattr(tree, operation)("../outside.txt")
    assert outside.read_text() == "private"


def test_symlink_escape_and_loops_are_not_followed(tmp_path):
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("private")
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
        (root / "loop").symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is not permitted on this host")
    tree = FileTree(root)
    nodes = list(flatten(tree.tree()["entries"]))
    assert len(nodes) == 2
    escape = next(row for row in nodes if row["name"] == "escape")
    assert escape["blocked"] and escape["type"] == "symlink"
    with pytest.raises(PermissionError):
        tree.read("escape/secret.txt")
    with pytest.raises(PermissionError):
        tree.write("escape/new.txt", "bad")
    assert not (outside / "new.txt").exists()


def test_in_root_file_symlink_can_be_read_without_tree_recursion(tmp_path):
    (tmp_path / "target.txt").write_text("safe")
    try:
        (tmp_path / "alias.txt").symlink_to(tmp_path / "target.txt")
    except OSError:
        pytest.skip("Symlink creation unavailable")
    tree = FileTree(tmp_path)
    assert tree.read("alias.txt")["content"] == "safe"
    assert next(row for row in tree.tree()["entries"] if row["name"] == "alias.txt")["children"] == []


def test_concurrent_writes_are_complete_and_preserve_mode(tmp_path):
    tree = FileTree(tmp_path)
    tree.write("file.txt", "initial")
    if os.name != "nt":
        (tmp_path / "file.txt").chmod(0o640)
    contents = [str(index) * 1000 for index in range(30)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda content: tree.write("file.txt", content), contents))
    assert tree.read("file.txt")["content"] in contents
    if os.name != "nt":
        assert (tmp_path / "file.txt").stat().st_mode & 0o777 == 0o640
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_file_and_non_directory_tree_are_explicit(tmp_path):
    tree = FileTree(tmp_path)
    with pytest.raises(FileNotFoundError):
        tree.read("missing")
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(NotADirectoryError):
        tree.tree("file.txt")
