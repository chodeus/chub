import importlib.util
import os
import pathlib
import signal
import stat

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "config_perms",
    pathlib.Path(__file__).parent.parent / "scripts" / "config_perms.py",
)
config_perms = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(config_perms)

pytestmark = pytest.mark.skipif(
    os.open not in os.supports_dir_fd, reason="needs openat()"
)


# Fixtures start at 0o400, stricter than every mode the locker sets: any
# looser start mode trips CodeQL py/overly-permissive-file.
def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def config_dir(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    for name in ("config.yml", "config.yml.legacy-2026", "chub.db", "unrelated.txt"):
        (cfg / name).write_text("x")
        os.chmod(cfg / name, 0o400)
    return cfg


def test_locks_secrets_and_leaves_other_files_alone(config_dir):
    rc = config_perms.main(["lock", str(config_dir)])
    assert rc == 0
    assert _mode(config_dir / "config.yml") == 0o600
    assert _mode(config_dir / "config.yml.legacy-2026") == 0o600
    assert _mode(config_dir / "chub.db") == 0o660
    assert _mode(config_dir / "unrelated.txt") == 0o400


def test_symlinked_subdir_cannot_redirect_the_chmod(config_dir, tmp_path):
    """A symlinked rclone/ must not let the fchmod reach outside CONFIG_DIR."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "rclone.conf").write_text("secret")
    os.chmod(outside / "rclone.conf", 0o400)
    (config_dir / "rclone").symlink_to(outside, target_is_directory=True)

    rc = config_perms.main(["lock", str(config_dir)])
    assert rc == 1
    assert _mode(outside / "rclone.conf") == 0o400


def test_symlinked_match_cannot_redirect_the_chmod(config_dir, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.chmod(outside, 0o400)
    (config_dir / "creds.json").symlink_to(outside)

    rc = config_perms.main(["lock", str(config_dir)])
    assert rc == 1
    assert _mode(outside) == 0o400


def test_a_fifo_does_not_block_startup(config_dir):
    """O_RDONLY on a FIFO blocks until a writer appears; O_NONBLOCK must prevent it."""
    os.mkfifo(config_dir / "pipe.json")

    def _timeout(signum, frame):
        raise AssertionError("config_perms blocked on a FIFO")

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(10)
    try:
        config_perms.main(["lock", str(config_dir)])
    finally:
        signal.alarm(0)
    assert _mode(config_dir / "config.yml") == 0o600


def test_missing_config_dir_reports_failure(tmp_path):
    rc = config_perms.main(["lock", str(tmp_path / "nope")])
    assert rc == 1


def test_chown_descends_into_subdirectories(config_dir, monkeypatch):
    """Every entry with the wrong owner is reached, at any depth."""
    deep = config_dir / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "nested.txt").write_text("x")

    seen = []

    def record(name, uid, gid, *, dir_fd=None, follow_symlinks=True):
        seen.append(name)

    monkeypatch.setattr(os, "chown", record)
    # A uid nothing owns, so every entry is considered wrong and gets visited.
    config_perms.main(["chown", str(config_dir), "424242", "424242"])

    assert "nested.txt" in seen
    assert "b" in seen
