"""Tests for the extended workspace and service tools."""
import pytest

from desktop.safety import Workspace


def test_edit_file_replaces_unique_occurrence(tmp_path):
    (tmp_path / "a.txt").write_text("alpha beta alpha\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    with pytest.raises(ValueError, match="expected 1 match"):
        workspace.edit_file("a.txt", search="alpha", replace="ALPHA")
    result = workspace.edit_file("a.txt", search="alpha", replace="ALPHA", count="all")
    assert result["matches"] == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ALPHA beta ALPHA\n"
    assert "ALPHA" in result["diff"]


def test_edit_file_regex_and_diff(tmp_path):
    (tmp_path / "b.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    result = workspace.edit_file("b.py", search=r"\d", replace="9", count="all", regex=True)
    assert result["matches"] == 2
    assert "y = 9" in (tmp_path / "b.py").read_text(encoding="utf-8")


def test_stat_and_append_and_tail(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.append_file("log.txt", "line 1\n")
    workspace.append_file("log.txt", "line 2\n")
    stat = workspace.stat_file("log.txt")
    assert stat["exists"] and stat["line_count"] == 2
    tail = workspace.tail_file("log.txt", lines=1)
    assert tail["content"].strip() == "line 2"


def test_make_delete_rename_copy(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.make_dir("sub/deep")
    workspace.write_file("sub/deep/a.txt", content="hello")
    copied = workspace.copy_file("sub/deep/a.txt", "sub/b.txt")
    assert copied["bytes"] == 5
    workspace.rename_file("sub/b.txt", "sub/c.txt")
    assert (tmp_path / "sub" / "c.txt").read_text(encoding="utf-8") == "hello"
    with pytest.raises(ValueError, match="not empty"):
        workspace.delete_file("sub")
    result = workspace.delete_file("sub", recursive=True)
    assert result["deleted"] and not (tmp_path / "sub").exists()
    with pytest.raises(PermissionError):
        workspace.delete_file(".", recursive=True)


def test_glob_grep_and_read_multiple(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("src/a.py", content="def one():\n    return 1\n")
    workspace.write_file("src/b.js", content="const two = 2;\n")
    hits = workspace.glob("src/**/*.py")
    assert [row["path"] for row in hits["matches"]] == ["src/a.py"]
    grep = workspace.grep("return", glob="*.py", context_lines=1)
    assert grep["matches"][0]["file"] == "src/a.py"
    batch = workspace.read_multiple_files(["src/a.py", "src/b.js"])
    assert all(item["ok"] for item in batch["files"])


def test_outline_and_find_symbol(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file(
        "mod.py",
        content="class A:\n    def m(self):\n        pass\n\ndef f():\n    return 1\n",
    )
    outline = workspace.outline("mod.py")
    assert {row["name"] for row in outline["symbols"]} == {"A", "f"}
    found = workspace.find_symbol("f")
    assert any(item["kind"] == "definition" for item in found["symbols"])


def test_diff_preview(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("d.txt", content="old\n")
    preview = workspace.diff_preview("d.txt", content="new\n")
    assert preview["exists"] and "-old" in preview["diff"] and "+new" in preview["diff"]
    assert (tmp_path / "d.txt").read_text(encoding="utf-8") == "old\n"
