import importlib.util
import os
import pathlib
import signal
import stat

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "lock_config_perms",
    pathlib.Path(__file__).parent.parent / "scripts" / "lock_config_perms.py",
)
lock_config_perms = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lock_config_perms)

pytestmark = pytest.mark.skipif(
    os.open not in os.supports_dir_fd, reason="needs openat()"
)


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def config_dir(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    for name in ("config.yml", "config.yml.legacy-2026", "chub.db", "unrelated.txt"):
        (cfg / name).write_text("x")
        os.chmod(cfg / name, 0o644)
    return cfg


def test_locks_secrets_and_leaves_other_files_alone(config_dir):
    assert lock_config_perms.main(str(config_dir)) == 0
    assert _mode(config_dir / "config.yml") == 0o600
    assert _mode(config_dir / "config.yml.legacy-2026") == 0o600
    assert _mode(config_dir / "chub.db") == 0o660
    assert _mode(config_dir / "unrelated.txt") == 0o644


def test_symlinked_subdir_cannot_redirect_the_chmod(config_dir, tmp_path):
    """A symlinked rclone/ must not let the fchmod reach outside CONFIG_DIR."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "rclone.conf").write_text("secret")
    os.chmod(outside / "rclone.conf", 0o644)
    (config_dir / "rclone").symlink_to(outside, target_is_directory=True)

    assert lock_config_perms.main(str(config_dir)) == 1
    assert _mode(outside / "rclone.conf") == 0o644


def test_symlinked_match_cannot_redirect_the_chmod(config_dir, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.chmod(outside, 0o644)
    (config_dir / "creds.json").symlink_to(outside)

    assert lock_config_perms.main(str(config_dir)) == 1
    assert _mode(outside) == 0o644


def test_a_fifo_does_not_block_startup(config_dir):
    """O_RDONLY on a FIFO blocks until a writer appears; O_NONBLOCK must prevent it."""
    os.mkfifo(config_dir / "pipe.json")

    def _timeout(signum, frame):
        raise AssertionError("lock_config_perms blocked on a FIFO")

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(10)
    try:
        lock_config_perms.main(str(config_dir))
    finally:
        signal.alarm(0)
    assert _mode(config_dir / "config.yml") == 0o600


def test_missing_config_dir_reports_failure(tmp_path):
    assert lock_config_perms.main(str(tmp_path / "nope")) == 1
