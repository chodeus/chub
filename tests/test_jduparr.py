import subprocess

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


def test_parse_duplicate_groups_ignores_jdupes_summary_lines():
    stdout = "\n".join(
        [
            "/media/a/movie.mkv",
            "/media/b/movie.mkv",
            "",
            "/media/c/show.mp4",
            "/media/d/show.mp4",
            "4 duplicate files (in 2 sets), occupying 100 bytes",
            "No duplicates found.",
        ]
    )

    assert Jduparr.parse_duplicate_groups(stdout) == [
        ["/media/a/movie.mkv", "/media/b/movie.mkv"],
        ["/media/c/show.mp4", "/media/d/show.mp4"],
    ]


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
        stdout = f"{duplicate_a}\n{duplicate_b}\n\n2 duplicate files (in 1 sets)"
        return completed(cmd, stdout=stdout)

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
        ["jdupes", "-r", "-M", "-X", "onlyext:mp4,mkv,avi", str(source_a), str(source_b)]
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
        if "-M" in cmd:
            return completed(
                cmd,
                stdout=f"{duplicate_a}\n{duplicate_b}\n\n2 duplicate files (in 1 sets)",
            )
        return completed(cmd, stdout=f"{duplicate_b} ----> {duplicate_a}\n")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(
        jduparr=JduparrConfig(source_dirs=[str(source_a), str(source_b)])
    )
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert len(calls) == 2
    assert "-M" in calls[0]
    assert "-L" in calls[1]
    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["sub_count"] == 1
    assert scan_item["linked_count"] == 1
    assert scan_item["status"] == "ok"


def test_no_duplicates_skips_link_command(tmp_path, monkeypatch):
    source = tmp_path / "movies"
    source.mkdir()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return completed(cmd, stdout="No duplicates found.\n")

    monkeypatch.setattr(jduparr_module.subprocess, "run", fake_run)
    config = ChubConfig(jduparr=JduparrConfig(source_dirs=[str(source)]))
    module, _logger = make_module(monkeypatch, config)

    module.run()

    assert len(calls) == 1
    assert "-M" in calls[0]
    scan_item = CapturingNotificationManager.sent[0][-1]
    assert scan_item["sub_count"] == 0
    assert scan_item["linked_count"] == 0
    assert "No duplicate files" in scan_item["field_message"]


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
    assert any("jdupes scan failed" in message for level, message in logger.records)


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
    assert any("unsafe source directory" in message for level, message in logger.records)


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
