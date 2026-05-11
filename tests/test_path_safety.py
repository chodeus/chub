"""Tests for backend/util/path_safety.py — filesystem access guard."""


from backend.util.path_safety import get_allowed_roots, is_path_allowed


def test_empty_config_has_only_config_dir(empty_config, tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    roots = get_allowed_roots(empty_config)
    assert any(str(r).startswith(str(tmp_path.resolve())) for r in roots)


def test_configured_roots_are_returned(config_with_roots):
    config, tmp_path = config_with_roots
    roots = get_allowed_roots(config)
    resolved = {str(r) for r in roots}
    assert str((tmp_path / "posters_src").resolve()) in resolved
    assert str((tmp_path / "posters_dst").resolve()) in resolved
    assert str((tmp_path / "nohl_src").resolve()) in resolved
    assert str((tmp_path / "jdup_src").resolve()) in resolved


def test_nonexistent_roots_are_filtered(empty_config):
    """Non-existent paths should not appear in the allowed roots."""
    empty_config.poster_renamerr.source_dirs = ["/this/does/not/exist/anywhere"]
    roots = get_allowed_roots(empty_config)
    for r in roots:
        assert str(r) != "/this/does/not/exist/anywhere"


def test_is_path_allowed_for_inside_root(config_with_roots):
    config, tmp_path = config_with_roots
    inside = tmp_path / "posters_src" / "movie.jpg"
    inside.write_text("x")
    assert is_path_allowed(str(inside), config)


def test_is_path_allowed_rejects_outside_root(config_with_roots, tmp_path):
    config, _ = config_with_roots
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    # outside is not in any allowed root
    assert not is_path_allowed(str(outside / "x.jpg"), config)


def test_is_path_allowed_rejects_traversal(config_with_roots, tmp_path):
    config, tmp_path = config_with_roots
    # ../ escape from one root
    sneaky = str(tmp_path / "posters_src" / ".." / "elsewhere" / "x.jpg")
    # elsewhere doesn't exist but resolve should still escape
    assert not is_path_allowed(sneaky, config)


def test_is_path_allowed_rejects_null_byte(config_with_roots):
    config, _ = config_with_roots
    assert not is_path_allowed("/tmp/foo\x00.jpg", config)


def test_is_path_allowed_rejects_empty_string(config_with_roots):
    config, _ = config_with_roots
    assert not is_path_allowed("", config)


def test_is_path_allowed_rejects_non_string(config_with_roots):
    config, _ = config_with_roots
    assert not is_path_allowed(None, config)  # type: ignore[arg-type]
    assert not is_path_allowed(123, config)  # type: ignore[arg-type]


def test_nohl_source_dirs_with_object_form(empty_config, tmp_path):
    """Nohl source dirs can be NohlSourceDir(path=...) objects."""
    from backend.util.config import NohlConfig, NohlSourceDir

    src = tmp_path / "nohl_obj"
    src.mkdir()
    empty_config.nohl = NohlConfig(
        source_dirs=[NohlSourceDir(path=str(src), mode="resolve")]
    )

    roots = get_allowed_roots(empty_config)
    assert any(str(r) == str(src.resolve()) for r in roots)
