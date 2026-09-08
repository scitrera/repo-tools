import pytest
from scitrera_repo_tools.version_sync.strategies.gowork import update_gowork


def workspace(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a/go.mod").write_text("module example.com/repo/a\n\ngo 1.26\nrequire example.com/repo/b v0.7.1\n")
    (tmp_path / "b/go.mod").write_text("module example.com/repo/b\n\ngo 1.26\n")
    p = tmp_path / "go.work"
    p.write_text("go 1.26\n\nuse (\n\t./a\n\t./b\n)\n")
    return p


def test_workspace_tracks_required_version_and_preserves_other_content(tmp_path):
    p = workspace(tmp_path)
    p.write_text(p.read_text() + "\nreplace example.com/other v1.0.0 => example.com/fork v1.0.0\n")
    original = p.read_text()
    assert update_gowork(p, "9.0.0", True)[0]
    assert p.read_text() == original
    assert update_gowork(p, "9.0.0", False)[0]
    assert "example.com/repo/b v0.7.1 => ./b" in p.read_text()
    assert "example.com/other v1.0.0 => example.com/fork v1.0.0" in p.read_text()
    assert not update_gowork(p, "9.0.0", True)[0]
    mod = tmp_path / "a/go.mod"
    mod.write_text(mod.read_text().replace("v0.7.1", "v0.7.2"))
    assert update_gowork(p, "9.0.0", False)[0]
    assert "v0.7.1" not in p.read_text()
    assert "example.com/repo/b v0.7.2 => ./b" in p.read_text()


def test_malformed_workspace_block_is_not_overwritten(tmp_path):
    p = workspace(tmp_path)
    p.write_text(p.read_text() + "// BEGIN repo-tools local module replacements\n")
    with pytest.raises(ValueError, match="malformed"):
        update_gowork(p, "0.7.1", False)
