import json
import subprocess
import threading

import backend.modules.jduparr as jduparr_module
import backend.util.base_module as base_module
from backend.modules.jduparr import Jduparr
from backend.util.config import ChubConfig, ConfigNotifications, JduparrConfig
from backend.util.notification import NotificationManager


class CapturingLogger:
    def __init__(self):
        self.records = []

    def get_adapter(self, _name):
        return self

    def debug(self, message, *args, **kwargs):
        self.records.append(("debug", str(message)))

    def info(self, message, *args, **kwargs):
        self.records.append(("info", str(message)))

    def warning(self, message, *args, **kwargs):
        self.records.append(("warning", str(message)))

    def error(self, message, *args, **kwargs):
        self.records.append(("error", str(message)))

    def log_outro(self):
        self.records.append(("info", "outro"))


class CapturingNotificationManager:
    init_args = []
    sent = []

    def __init__(self, config, logger, module_name="main"):
        self.__class__.init_args.append((config, module_name))

    def send_notification(self, output):
        self.__class__.sent.append(output)


def make_module(monkeypatch, config):
    logger = CapturingLogger()
    monkeypatch.setattr(base_module, "load_config", lambda: config)
    CapturingNotificationManager.init_args = []
    CapturingNotificationManager.sent = []
    monkeypatch.setattr(jduparr_module, "NotificationManager", CapturingNotificationManager)
    return Jduparr(logger=logger), logger


def completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def json_stdout(*match_sets):
    """Build a ``jdupes --json`` stdout payload from lists of file paths."""
    return json.dumps(
        {
            "jdupesVersion": "1.31.1",
            "matchSets": [
                {"fileSize": 10, "fileList": [{"filePath": p} for p in paths]}
                for paths in match_sets
            ],
        }
    )


def has_record(logger, needle):
    return any(needle in message for _level, message in logger.records)


# ---------------------------------------------------------------------------
# Parsing (now JSON-based)
# ---------------------------------------------------------------------------


def test_parse_duplicate_groups_from_json():
    stdout = json_stdout(
        ["/media/a/movie.mkv", "/media/b/movie.mkv"],
        ["/media/c/show.mp4", "/media/d/show.mp4", "/media/e/show.mp4"],
    )

    assert Jduparr.parse_duplicate_groups(stdout) == [
        ["/media/a/movie.mkv", "/media/b/movie.mkv"],
        ["/media/c/show.mp4", "/media/d/show.mp4", "/media/e/show.mp4"],
    ]


def test_parse_duplicate_groups_drops_single_file_sets_and_handles_empty():
    # A 1-file matchSet is not a duplicate group and must be dropped.
    stdout = json_stdout(["/media/a/only.mkv"])
    assert Jduparr.parse_duplicate_groups(stdout) == []
    # Empty / no-dupes output.
    assert Jduparr.parse_duplicate_groups(json_stdout()) == []
    assert Jduparr.parse_duplicate_groups("") == []


def test_parse_duplicate_groups_tolerates_malformed_json():
    assert Jduparr.parse_duplicate_groups("not json at all") == []
    assert Jduparr.parse_duplicate_groups('{"matchSets": "oops"}') == []


def test_path_that_looks_like_summary_text_is_not_dropped():
    # Regression: with the old line-based parser a path containing words like
    # "duplicate files" was mistaken for a summary line and dropped. JSON
    # parsing keys off structure, so such paths survive.
    stdout = json_stdout(
        ["/media/12 files/a.mkv", "/media/duplicate files/a.mkv"],
    )
    assert Jduparr.parse_duplicate_groups(stdout) == [
        ["/media/12 files/a.mkv", "/media/duplicate files/a.mkv"],
    ]


# ---------------------------------------------------------------------------
# Scan / link flow
# ---------------------------------------------------------------------------


def test_dry_run_scans_all_source_dirs_once_and_does_not_link(tmp_path, monkeypatch):
    source_a = tmp_path / "movies-a"
    source_b = tmp_path / "movies-b"
    source_a.mkdir()
    source_b.mkdir()
    duplicate_a = source_a / "Movie.mkv"
    duplicate_b = source_b / "Movie.mkv"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return completed(cmd, stdout=json_stdout([str(duplicate_a), str(duplicate_b)]))

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(
        jduparr=JduparrConfig(
            dry_run=True,
            source_dirs=[str(source_a), str(source_b)],
        )
    )
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert calls == [
        ["jdupes", "-r", "--json", "-X", "onlyext:mp4,mkv,avi", str(source_a), str(source_b)]
    ]
    assert CapturingNotificationManager.init_args == [(config, "jduparr")]
    output = CapturingNotificationManager.sent[0]
    scan_item = output[-1]
    assert scan_item["source_dirs"] == [str(source_a), str(source_b)]
    assert scan_item["sub_count"] == 1
    assert scan_item["linked_count"] == 0
    assert scan_item["output"] == [str(duplicate_a), str(duplicate_b)]
    assert "would be relinked" in scan_item["field_message"]


def test_non_dry_run_links_only_after_successful_scan(tmp_path, monkeypatch):
    source_a = tmp_path / "movies-a"
    source_b = tmp_path / "movies-b"
    source_a.mkdir()
    source_b.mkdir()
    duplicate_a = source_a / "Movie.mkv"
    duplicate_b = source_b / "Movie.mkv"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--json" in cmd:
            return completed(
                cmd, stdout=json_stdout([str(duplicate_a), str(duplicate_b)])
            )
        # jdupes -L is silent on success.
        return completed(cmd, stdout="")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(
        jduparr=JduparrConfig(source_dirs=[str(source_a), str(source_b)])
    )
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert len(calls) == 2
    assert "--json" in calls[0]
    assert "-L" in calls[1]
    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["sub_count"] == 1
    assert scan_item["linked_count"] == 1
    assert scan_item["status"] == "ok"


def test_silent_link_success_reports_all_candidates_relinked(tmp_path, monkeypatch):
    # A 3-file set => 2 relink candidates. jdupes -L prints nothing on success,
    # so linked_count must equal the candidate count derived from the scan.
    source = tmp_path / "movies"
    source.mkdir()
    a, b, c = (source / "a.mkv"), (source / "b.mkv"), (source / "c.mkv")

    def fake_run(cmd, **kwargs):
        if "--json" in cmd:
            return completed(cmd, stdout=json_stdout([str(a), str(b), str(c)]))
        return completed(cmd, stdout="")  # silent success

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, _logger = make_module(monkeypatch, config)

    module.run()

    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["sub_count"] == 2
    assert scan_item["linked_count"] == 2
    assert scan_item["status"] == "ok"
    assert "2 files relinked" in scan_item["field_message"]


def test_no_duplicates_skips_link_command(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return completed(cmd, stdout=json_stdout())  # empty matchSets

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert len(calls) == 1
    assert "--json" in calls[0]
    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["sub_count"] == 0
    assert scan_item["linked_count"] == 0
    assert "No duplicate files" in scan_item["field_message"]


# ---------------------------------------------------------------------------
# Error / failure paths
# ---------------------------------------------------------------------------


def test_scan_failure_reports_error_and_does_not_link(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return completed(cmd, returncode=2, stderr="permission denied")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    assert len(calls) == 1
    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["status"] == "error"
    assert scan_item["sub_count"] == 0
    assert "permission denied" in scan_item["error"]
    assert has_record(logger, "jdupes scan failed")


def test_link_failure_reports_error_and_preserves_scan_results(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    a, b = (source / "a.mkv"), (source / "b.mkv")

    def fake_run(cmd, **kwargs):
        if "--json" in cmd:
            return completed(cmd, stdout=json_stdout([str(a), str(b)]))
        return completed(cmd, returncode=1, stderr="cannot move link target")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["status"] == "error"
    assert scan_item["linked_count"] == 0
    assert scan_item["sub_count"] == 1  # scan results preserved
    assert "hardlink failed" in scan_item["error"]
    assert "relinking failed" in scan_item["field_message"]
    assert has_record(logger, "jdupes hardlink failed")


def test_jdupes_not_found_on_scan_notifies(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("jdupes")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    assert len(CapturingNotificationManager.sent) == 1
    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["status"] == "error"
    assert "jdupes not found" in scan_item["error"]
    assert has_record(logger, "jdupes not found")


def test_jdupes_not_found_on_link_preserves_scan_and_notifies(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    a, b = (source / "a.mkv"), (source / "b.mkv")

    def fake_run(cmd, **kwargs):
        if "--json" in cmd:
            return completed(cmd, stdout=json_stdout([str(a), str(b)]))
        raise FileNotFoundError("jdupes")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, _logger = make_module(monkeypatch, config)

    module.run()

    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["status"] == "error"
    assert scan_item["sub_count"] == 1  # scan results preserved
    assert "jdupes not found" in scan_item["error"]


def test_scan_timeout_reports_error_and_notifies(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["status"] == "error"
    assert "timed out" in scan_item["error"]
    assert has_record(logger, "timed out")


def test_subprocess_run_called_with_timeout(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    seen_kwargs = []

    def fake_run(cmd, **kwargs):
        seen_kwargs.append(kwargs)
        return completed(cmd, stdout=json_stdout())

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert seen_kwargs and seen_kwargs[0].get("timeout") == jduparr_module.JDUPES_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Path-safety / config validation
# ---------------------------------------------------------------------------


def test_unsafe_source_dir_is_rejected_before_jdupes_runs(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise AssertionError("jdupes should not run for unsafe source dirs")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=["-not-a-path"]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    output = CapturingNotificationManager.sent[0]
    assert output[0]["status"] == "error"
    assert "unsafe source directory" in output[0]["error"]
    assert has_record(logger, "unsafe source directory")


def test_missing_source_dir_reports_error_and_skips_jdupes(tmp_path, monkeypatch):
    ghost = tmp_path / "does-not-exist"

    def fake_run(cmd, **kwargs):
        raise AssertionError("jdupes should not run for a nonexistent dir")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(ghost)]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    output = CapturingNotificationManager.sent[0]
    assert output[0]["status"] == "error"
    assert "does not exist" in output[0]["error"]
    assert has_record(logger, "path does not exist")


def test_empty_source_dirs_logs_error_and_does_not_notify(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise AssertionError("jdupes should not run with no source dirs")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[]))
    module, logger = make_module(monkeypatch, config)

    module.run()

    assert CapturingNotificationManager.sent == []
    assert has_record(logger, "No source directories")


def test_cancellation_before_scan_skips_jdupes(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()

    def fake_run(cmd, **kwargs):
        raise AssertionError("jdupes should not run after cancellation")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, logger = make_module(monkeypatch, config)

    event = threading.Event()
    event.set()
    module.set_cancel_event(event)

    module.run()

    assert CapturingNotificationManager.sent == []
    assert has_record(logger, "Cancellation requested")


def test_unsafe_hash_database_is_rejected_before_jdupes(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()

    def fake_run(cmd, **kwargs):
        raise AssertionError("jdupes should not run for an unsafe hash_database")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(
        jduparr=JduparrConfig(source_dirs=[str(source)], hash_database="-evil")
    )
    module, logger = make_module(monkeypatch, config)

    module.run()

    assert has_record(logger, "unsafe hash_database")


def test_hash_database_missing_parent_dir_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    bad_hash_db = tmp_path / "no-such-dir" / "hashes.db"

    def fake_run(cmd, **kwargs):
        raise AssertionError("jdupes should not run when hash_database parent missing")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(
        jduparr=JduparrConfig(source_dirs=[str(source)], hash_database=str(bad_hash_db))
    )
    module, logger = make_module(monkeypatch, config)

    module.run()

    assert has_record(logger, "parent directory does not exist")


def test_valid_hash_database_is_injected_into_both_commands(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    hash_db = tmp_path / "hashes.db"  # parent (tmp_path) exists
    a, b = (source / "a.mkv"), (source / "b.mkv")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--json" in cmd:
            return completed(cmd, stdout=json_stdout([str(a), str(b)]))
        return completed(cmd, stdout="")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(
        jduparr=JduparrConfig(source_dirs=[str(source)], hash_database=str(hash_db))
    )
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert len(calls) == 2
    for cmd in calls:
        assert "-y" in cmd
        assert cmd[cmd.index("-y") + 1] == str(hash_db)


# ---------------------------------------------------------------------------
# Notification integration (unchanged contract)
# ---------------------------------------------------------------------------


def test_notification_manager_reads_jduparr_targets_from_full_config(monkeypatch):
    config = ChubConfig(
        jduparr=JduparrConfig(dry_run=True),
        notifications=ConfigNotifications(
            jduparr={
                "discord": {
                    "webhook": "https://discord.com/api/webhooks/1/token",
                }
            }
        ),
    )
    manager = NotificationManager(config, CapturingLogger(), module_name="jduparr")

    from backend.util.notification import DiscordConfig

    assert manager.module_config.dry_run is True
    assert manager.collect_valid_targets() == {
        "discord": {
            "webhook": "https://discord.com/api/webhooks/1/token",
            "bot_name": None,
            "color": None,
        }
    }

    monkeypatch.setattr(
        manager,
        "send_and_log_response",
        lambda _label, _hook, _payload: (True, "ok"),
    )
    ok, message = manager.send_discord_notification(
        DiscordConfig(webhook="https://discord.com/api/webhooks/1/token"),
        "Jduparr",
        [
            {
                "source_dir": "/media",
                "source_dirs": ["/media"],
                "field_message": "✅ No duplicate files discovered...",
                "output": [],
                "sub_count": 0,
                "linked_count": 0,
            }
        ],
    )

    assert ok is True
    assert message == "ok"
