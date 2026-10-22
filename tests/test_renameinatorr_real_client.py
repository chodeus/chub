"""Renameinatorr through the real SonarrClient, with only the HTTP session faked."""

import posixpath
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from backend.modules.renameinatorr import Renameinatorr
from backend.util import arr as arr_mod
from backend.util.arr import RetryHandler, SonarrClient

ROOT = "/tv"


class _Silent:
    def _noop(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = _noop


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.headers = {}
        self.text = ""
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeSonarr:
    """An in-memory Sonarr behind `session.request`: series, folders, files, commands, tags."""

    def __init__(self):
        self.series = {}
        self.expected = {}
        self.disk = {}
        self.records = {}
        self.previews = {}
        self.tags = []
        self.commands = []
        self.down = set()
        self.gone = set()
        self.log = []
        self.timeout = 5

    def add(self, sid, folder, expected=None, files=("Season 01/a.mkv",), renames=None):
        path = f"{ROOT}/{folder}"
        self.series[sid] = {
            "id": sid,
            "title": f"Show {sid}",
            "year": 2011,
            "path": path,
            "rootFolderPath": ROOT,
            "tags": [],
        }
        self.expected[sid] = expected or folder
        self.disk[path] = set(files)
        self.records[sid] = {i + 1000 * sid: f for i, f in enumerate(sorted(files))}
        self.previews[sid] = dict(renames or {})

    def _command(self, name, **extra):
        cmd = {
            "id": len(self.commands) + 1,
            "name": name,
            "status": "completed",
            **extra,
        }
        self.commands.append(cmd)
        return cmd

    def request(
        self, method, endpoint, headers=None, json=None, params=None, timeout=None
    ):
        url = urlparse(endpoint)
        path = url.path.removeprefix("/api/v3")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        query.update(params or {})
        self.log.append((method, path, json if json is not None else query))
        for prefix in self.down:
            if path.startswith(prefix):
                return _Response(503)
        if (path, str(query.get("seriesId"))) in self.gone:
            return _Response(404)
        if method == "GET":
            return _Response(200, self._get(path, query))
        if method == "POST" and path == "/command":
            return _Response(201, self._post_command(json))
        if method == "POST" and path == "/tag":
            tag = {"id": len(self.tags) + 1, "label": json["label"]}
            self.tags.append(tag)
            return _Response(201, tag)
        if method == "PUT" and path == "/series/editor":
            return _Response(202, self._editor(json))
        return _Response(404)

    def _get(self, path, q):
        if path == "/series":
            return [dict(s) for s in self.series.values()]
        if path == "/tag":
            return list(self.tags)
        if path == "/rename":
            sid = int(q["seriesId"])
            return [
                {"seriesId": sid, "existingPath": o, "newPath": n}
                for o, n in self.previews[sid].items()
            ]
        if path.startswith("/series/") and path.endswith("/folder"):
            return {"folder": self.expected[int(path.split("/")[2])]}
        if path == "/filesystem":
            parent = q["path"].rstrip("/")
            names = {
                posixpath.basename(p)
                for p in self.disk
                if posixpath.dirname(p) == parent
            }
            return {
                "directories": [{"name": n, "type": "folder"} for n in sorted(names)],
                "files": [],
            }
        if path == "/filesystem/mediafiles":
            folder = q["path"]
            return [
                {
                    "path": f"{folder}/{f}",
                    "relativePath": f,
                    "name": posixpath.basename(f),
                }
                for f in sorted(self.disk.get(folder, ()))
            ]
        if path == "/episodefile":
            sid = int(q["seriesId"])
            return [
                {"id": i, "seriesId": sid, "relativePath": r}
                for i, r in self.records[sid].items()
            ]
        if path == "/command":
            return list(self.commands)
        if path.startswith("/command/"):
            return self.commands[int(path.split("/")[2]) - 1]
        raise AssertionError(f"unexpected GET {path}")

    def _post_command(self, body):
        name = body["name"]
        if name == "RenameSeries":
            for sid in body["seriesIds"]:
                files = self.disk[self.series[sid]["path"]]
                for old, new in self.previews[sid].items():
                    files.discard(old)
                    files.add(new)
                    self.records[sid] = {
                        k: new if v == old else v for k, v in self.records[sid].items()
                    }
                self.previews[sid] = {}
        return self._command(name)

    def _editor(self, body):
        ids = body["seriesIds"]
        if "applyTags" in body:
            for sid in ids:
                tags = self.series[sid]["tags"]
                if body["applyTags"] == "add":
                    tags.extend(t for t in body["tags"] if t not in tags)
                else:
                    self.series[sid]["tags"] = [
                        t for t in tags if t not in body["tags"]
                    ]
            return [self.series[s] for s in ids]
        if body.get("moveFiles"):
            for sid in ids:
                old = self.series[sid]["path"]
                new = f"{body['rootFolderPath'].rstrip('/')}/{self.expected[sid]}"
                self.disk[new] = self.disk.pop(old)
                self.series[sid]["path"] = new
            self._command("BulkMoveSeries")
        return [self.series[s] for s in ids]


def _client(monkeypatch, fake):
    monkeypatch.setattr(arr_mod.time, "sleep", lambda _s: None)
    client = SonarrClient.__new__(SonarrClient)
    client.url = "http://sonarr.test"
    client.api = "k"
    client.logger = _Silent()
    client.headers = {}
    client.instance_name = "sonarr"
    client.connect_status = True
    client.retry_handler = RetryHandler()
    client.session = fake
    client.timeout = 5
    return client


def _run(client, **overrides):
    cfg = dict(
        count=0,
        radarr_count=0,
        sonarr_count=0,
        tag_name="",
        ignore_tags="",
        enable_batching=False,
        dry_run=False,
        rename_folders=True,
        refresh_before_rename=False,
    )
    cfg.update(overrides)
    m = object.__new__(Renameinatorr)
    m._cancel_event = None
    data, stopped = m.process_instance(
        client, "sonarr", SimpleNamespace(**cfg), _Silent()
    )
    return {item["title"]: item for item in data}, stopped


@pytest.fixture
def sonarr(monkeypatch):
    fake = _FakeSonarr()
    fake.headers = {}
    fake.close = lambda: None
    monkeypatch.setattr(arr_mod.requests, "Session", lambda: fake)
    return fake, _client(monkeypatch, fake)


def test_control_renames_files_and_moves_folder_through_the_real_client(sonarr):
    fake, client = sonarr
    fake.add(
        1,
        "Show",
        "Show (2011)",
        renames={"Season 01/a.mkv": "Season 01/Show - S01E01.mkv"},
    )

    report, stopped = _run(client)

    assert stopped is None
    assert fake.series[1]["path"] == "/tv/Show (2011)"
    assert fake.disk["/tv/Show (2011)"] == {"Season 01/Show - S01E01.mkv"}
    assert report["Show 1"]["new_path_name"] == "Show (2011)"
    assert report["Show 1"]["problems"] == []


@pytest.mark.parametrize("down", ["/filesystem", "/series/1/folder"])
def test_a_transient_read_failure_does_not_tag_the_item_as_done(sonarr, down):
    fake, client = sonarr
    fake.add(1, "Show", "Show (2011)")
    fake.down.add(down)

    report, stopped = _run(client, tag_name="renamed")

    assert "this batch wasn't renamed" in stopped
    assert fake.series[1]["path"] == "/tv/Show"
    tagged = fake.series[1]["tags"]
    assert tagged == [], f"stopped by an outage ({stopped}) yet tagged done"


def test_a_case_only_move_that_leaves_files_behind_is_reported(sonarr):
    fake, client = sonarr
    fake.add(
        1, "show (2011)", "Show (2011)", files=("Season 01/a.mkv", "Season 01/b.mkv")
    )
    original = fake._editor

    def leave_one_behind(body):
        result = original(body)
        if body.get("moveFiles"):
            fake.disk["/tv/Show (2011)"].discard("Season 01/b.mkv")
            fake.disk["/tv/show (2011)"] = {"Season 01/b.mkv"}
        return result

    fake._editor = leave_one_behind

    report, stopped = _run(client)

    assert fake.disk["/tv/show (2011)"] == {"Season 01/b.mkv"}
    problems = report["Show 1"]["problems"]
    assert any("left behind" in p for p in problems), problems
    assert stopped


def test_two_items_wanting_one_folder_move_only_the_first(sonarr):
    fake, client = sonarr
    fake.add(1, "Show A", "Show (2011)")
    fake.add(2, "Show B", "Show (2011)")

    report, _ = _run(client)

    assert fake.series[1]["path"] == "/tv/Show (2011)"
    assert fake.series[2]["path"] == "/tv/Show B"
    assert report["Show 2"]["blocked"] == "another item already uses that folder"


def test_swapped_folder_names_are_both_blocked(sonarr):
    fake, client = sonarr
    fake.add(1, "X", "Y")
    fake.add(2, "Y", "X")

    report, _ = _run(client)

    assert fake.series[1]["path"] == "/tv/X"
    assert fake.series[2]["path"] == "/tv/Y"
    assert report["Show 1"]["blocked"] and report["Show 2"]["blocked"]


def test_verify_read_failure_after_rename_stops_and_flags(sonarr):
    fake, client = sonarr
    fake.add(1, "Show", renames={"Season 01/a.mkv": "Season 01/b.mkv"})
    original = fake._post_command

    def then_go_down(body):
        result = original(body)
        if body["name"] == "RenameSeries":
            fake.down.add("/series")
        return result

    fake._post_command = then_go_down

    report, stopped = _run(client)

    assert fake.disk["/tv/Show"] == {"Season 01/b.mkv"}
    assert stopped
    assert report["Show 1"]["problems"] == [
        "its files couldn't be read after the change"
    ]


def test_a_series_deleted_after_its_rename_is_a_problem_not_a_crash(sonarr):
    fake, client = sonarr
    fake.add(1, "One", renames={"Season 01/a.mkv": "Season 01/b.mkv"})
    fake.add(2, "Two", renames={"Season 01/a.mkv": "Season 01/c.mkv"})
    original = fake._post_command

    def delete_two(body):
        result = original(body)
        if body["name"] == "RenameSeries":
            fake.gone.add(("/episodefile", "2"))
        return result

    fake._post_command = delete_two

    report, stopped = _run(client)

    assert fake.disk["/tv/One"] == {"Season 01/b.mkv"}
    assert report["Show 1"]["file_info"] == {"a.mkv": "b.mkv"}
    assert report["Show 2"]["problems"]


def test_a_refresh_that_reverts_a_move_stops_the_run(sonarr):
    fake, client = sonarr
    fake.add(1, "Show", "Show (2011)")
    original = fake._editor

    def stale_refresh_saves_old_path(body):
        result = original(body)
        if body.get("moveFiles"):
            fake.series[1]["path"] = "/tv/Show"
        return result

    fake._editor = stale_refresh_saves_old_path

    report, stopped = _run(client)

    assert fake.disk["/tv/Show (2011)"] == {"Season 01/a.mkv"}
    assert stopped
    assert (
        "its folder wasn't renamed (see the arr's logs)" in report["Show 1"]["problems"]
    )


def test_held_summary_matches_why_a_folder_was_held(sonarr):
    from backend.util.notification_formatting import format_for_discord

    fake, client = sonarr
    fake.add(1, "Show (2011)", "Show (2011) {tvdb-}")

    report, _ = _run(client)
    output = {
        "sonarr": {
            "server_name": "sonarr",
            "data": list(report.values()),
            "stopped": None,
        }
    }
    embeds, _ = format_for_discord(SimpleNamespace(module_name="renameinatorr"), output)
    summary = [f["value"] for e in embeds.values() for f in e if f["name"] == "Summary"]

    assert report["Show 1"]["held"] == "the new name has an empty tvdb id"
    assert "lose" not in summary[0], summary[0]


def test_ignore_tags_keep_an_item_out_of_renames_and_moves(sonarr):
    fake, client = sonarr
    fake.tags.append({"id": 1, "label": "skip"})
    fake.add(1, "Show", "Show (2011)", renames={"Season 01/a.mkv": "Season 01/b.mkv"})
    fake.series[1]["tags"] = [1]

    report, _ = _run(client, ignore_tags="skip")

    assert fake.series[1]["path"] == "/tv/Show"
    assert fake.disk["/tv/Show"] == {"Season 01/a.mkv"}
    assert "Show 1" not in report


def test_tag_cycle_reaches_the_next_item_on_the_next_run(sonarr):
    fake, client = sonarr
    fake.add(1, "One", "One (2011)")
    fake.add(2, "Two", "Two (2011)")

    _run(client, tag_name="renamed", count=1)
    report, _ = _run(client, tag_name="renamed", count=1)

    assert list(report) == ["Show 2"]
    assert fake.series[2]["path"] == "/tv/Two (2011)"


def test_ignore_tag_holds_when_the_tag_list_is_unreadable(sonarr):
    fake, client = sonarr
    fake.tags.append({"id": 1, "label": "skip"})
    fake.add(1, "Show", "Show (2011)", renames={"Season 01/a.mkv": "Season 01/b.mkv"})
    fake.series[1]["tags"] = [1]
    fake.down.add("/tag")

    report, stopped = _run(client, ignore_tags="skip")

    assert "ignore tags couldn't be applied" in stopped
    path = fake.series[1]["path"]
    files = fake.disk.get("/tv/Show")
    assert path == "/tv/Show", f"ignored item was moved to {path}"
    assert files == {"Season 01/a.mkv"}, f"ignored item's files renamed: {files}"


def test_a_persistently_failing_item_does_not_starve_the_tag_rotation(sonarr):
    fake, client = sonarr
    fake.add(1, "One", renames={"Season 01/a.mkv": "Season 01/b.mkv"})
    fake.add(2, "Two", "Two (2011)")
    original = fake._post_command

    def never_rename_one(body):
        if body["name"] == "RenameSeries":
            body = dict(body, seriesIds=[s for s in body["seriesIds"] if s != 1])
        return original(body)

    fake._post_command = never_rename_one

    for _ in range(3):
        report, _ = _run(client, tag_name="renamed", count=1)

    assert report["Show 1"]["problems"]
    path = fake.series[2]["path"]
    assert path == "/tv/Two (2011)", f"after 3 runs item 2 never reached: {path}"


def test_a_cancelled_run_does_not_report_unapplied_renames(sonarr):
    fake, client = sonarr
    fake.add(1, "Show", renames={"Season 01/a.mkv": "Season 01/b.mkv"})
    event = threading.Event()
    original = fake._get

    def cancel_during_prefetch(path, q):
        if path == "/rename":
            event.set()
        return original(path, q)

    fake._get = cancel_during_prefetch

    m = object.__new__(Renameinatorr)
    m._cancel_event = event
    cfg = SimpleNamespace(
        count=0,
        radarr_count=0,
        sonarr_count=0,
        tag_name="",
        ignore_tags="",
        enable_batching=False,
        dry_run=False,
        rename_folders=False,
        refresh_before_rename=False,
    )
    data, _ = m.process_instance(client, "sonarr", cfg, _Silent())

    assert fake.disk["/tv/Show"] == {"Season 01/a.mkv"}
    reported = data[0]["file_info"]
    assert reported == {}, f"report lists renames that never ran: {reported}"


RENAME = {"Season 01/a.mkv": "Season 01/b.mkv"}


def _fail_requests(fake, matches, status, times=None):
    """Answer requests for which `matches(method, path, body)` holds with `status`, `times` times (None: always)."""
    original = fake.request
    left = [times]

    def request(method, endpoint, headers=None, json=None, params=None, timeout=None):
        path = endpoint.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path.removeprefix("api/v3/").split("?")[0]
        if matches(method, path, json) and left[0] != 0:
            if left[0] is not None:
                left[0] -= 1
            return _Response(status)
        return original(method, endpoint, headers, json, params, timeout)

    fake.request = request


def test_an_item_the_arr_has_no_folder_name_for_does_not_stall_the_rotation(sonarr):
    fake, client = sonarr
    fake.add(1, "One", "One (2011)", renames=RENAME)
    fake.add(2, "Two", "Two (2011)")
    _fail_requests(fake, lambda m, p, b: p == "/series/1/folder", 404)

    stops = [_run(client, tag_name="renamed", count=1)[1] for _ in range(3)]

    files = fake.disk["/tv/One"]
    two = fake.series[2]["path"]
    assert files == {"Season 01/b.mkv"} and two == "/tv/Two (2011)", (
        f"after 3 runs: item 1 files {files}, item 2 at {two}; stops: {stops}"
    )


@pytest.mark.parametrize(
    "outage",
    [
        lambda m, p, b: p == "/filesystem/mediafiles",
        lambda m, p, b: p == "/episodefile",
    ],
    ids=["mediafiles", "episodefile"],
)
def test_a_transient_snapshot_read_failure_is_retried_next_run(sonarr, outage):
    fake, client = sonarr
    fake.add(1, "One", renames=RENAME)
    fake.add(2, "Two")
    _fail_requests(fake, outage, 503, times=5)

    _, first_stop = _run(client, tag_name="renamed", count=1)
    _run(client, tag_name="renamed", count=1)

    files = fake.disk["/tv/One"]
    assert files == {"Season 01/b.mkv"}, (
        f"a 503 blip (first run stopped={first_stop!r}) left item 1 unrenamed "
        f"and tagged {fake.series[1]['tags']} until the next cycle"
    )


def test_a_failed_rename_request_is_retried_next_run(sonarr):
    fake, client = sonarr
    fake.add(1, "One", renames=RENAME)
    fake.add(2, "Two")
    _fail_requests(
        fake,
        lambda m, p, b: m == "POST" and (b or {}).get("name") == "RenameSeries",
        503,
        times=1,
    )

    _, first_stop = _run(client, tag_name="renamed", count=1)
    _run(client, tag_name="renamed", count=1)

    files = fake.disk["/tv/One"]
    assert files == {"Season 01/b.mkv"}, (
        f"rename POST got 503 (first run stopped={first_stop!r}); item 1 tagged "
        f"{fake.series[1]['tags']} and never retried: {files}"
    )


def test_a_transient_folder_name_failure_on_one_item_is_retried_next_run(sonarr):
    fake, client = sonarr
    fake.add(1, "One", "One (2011)")
    fake.add(2, "Two", "Two (2011)")
    fake.add(3, "Three", "Three (2011)")
    _fail_requests(fake, lambda m, p, b: p == "/series/1/folder", 503, times=5)

    _, first_stop = _run(client, tag_name="renamed", count=2)
    _run(client, tag_name="renamed", count=2)

    path = fake.series[1]["path"]
    assert path == "/tv/One (2011)", (
        f"a 503 blip (first run stopped={first_stop!r}) left item 1 at {path}, "
        f"tagged {fake.series[1]['tags']} until the next cycle"
    )
