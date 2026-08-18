"""ensure_type_subfolders — split a parent Drive folder into the artwork layout.

Every rclone call is stubbed; these pin the contract (create only what's missing,
return real ids, never touch existing content) without going near Drive.
"""

import json

import pytest

from backend.util.cl2k import gdrive_upload


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Sync:
    gdrive_sa_location = None
    token = '{"access_token":"x","refresh_token":"y"}'
    client_id = ""
    client_secret = ""


class _Log:
    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass


def _dirs(*names):
    return json.dumps([{"Name": n, "ID": f"ID_{n}"} for n in names])


@pytest.fixture
def rclone(monkeypatch):
    """Record every rclone invocation and script its output."""
    calls = []
    scripted = {"lsjson": [], "mkdir": _Result()}

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        verb = cmd[1]
        if verb == "lsjson":
            queue = scripted["lsjson"]
            return queue.pop(0) if queue else _Result(stdout="[]")
        if verb == "mkdir":
            return scripted["mkdir"]
        return _Result()

    monkeypatch.setattr(gdrive_upload.subprocess, "run", fake_run)
    monkeypatch.setattr(gdrive_upload, "_rclone_path", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(gdrive_upload, "_ensure_remote", lambda *a, **kw: None)
    return {"calls": calls, "scripted": scripted}


def test_creates_all_three_when_the_parent_is_empty(rclone):
    rclone["scripted"]["lsjson"] = [
        _Result(stdout="[]"),  # first listing: nothing there
        _Result(stdout=_dirs("logos", "backgrounds", "squareart")),  # after mkdir
    ]
    out = gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())

    assert [s["image_type"] for s in out] == ["logo", "background", "squareart"]
    assert [s["name"] for s in out] == ["logos", "backgrounds", "squareart"]
    assert all(s["created"] for s in out)
    assert {s["folder_id"] for s in out} == {"ID_logos", "ID_backgrounds", "ID_squareart"}
    mkdirs = [c for c in rclone["calls"] if c[1] == "mkdir"]
    assert len(mkdirs) == 3


def test_reuses_existing_subfolders_and_creates_none(rclone):
    rclone["scripted"]["lsjson"] = [_Result(stdout=_dirs("logos", "backgrounds", "squareart"))]
    out = gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())

    assert not any(s["created"] for s in out)
    assert [c for c in rclone["calls"] if c[1] == "mkdir"] == []
    # Only ONE listing when nothing was created — no pointless second round-trip.
    assert len([c for c in rclone["calls"] if c[1] == "lsjson"]) == 1


def test_creates_only_the_missing_one(rclone):
    rclone["scripted"]["lsjson"] = [
        _Result(stdout=_dirs("logos", "backgrounds")),
        _Result(stdout=_dirs("logos", "backgrounds", "squareart")),
    ]
    out = gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())

    created = [s["name"] for s in out if s["created"]]
    assert created == ["squareart"]
    mkdirs = [c for c in rclone["calls"] if c[1] == "mkdir"]
    assert len(mkdirs) == 1
    assert "posters:squareart" in mkdirs[0]


def test_unrelated_sibling_folders_are_left_alone(rclone):
    """A parent holding other folders must not be reorganised — only add ours."""
    rclone["scripted"]["lsjson"] = [
        _Result(stdout=_dirs("posters", "archive")),
        _Result(stdout=_dirs("posters", "archive", "logos", "backgrounds", "squareart")),
    ]
    out = gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())

    assert len(out) == 3
    made = {c[2] for c in rclone["calls"] if c[1] == "mkdir"}
    assert made == {"posters:logos", "posters:backgrounds", "posters:squareart"}
    # Nothing destructive is ever issued.
    verbs = {c[1] for c in rclone["calls"]}
    assert verbs.isdisjoint({"delete", "deletefile", "purge", "move", "moveto", "sync"})


def test_raises_when_mkdir_fails(rclone):
    rclone["scripted"]["lsjson"] = [_Result(stdout="[]")]
    rclone["scripted"]["mkdir"] = _Result(returncode=1, stderr="quota exceeded")
    with pytest.raises(RuntimeError, match="mkdir"):
        gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())


def test_raises_when_listing_fails(rclone):
    rclone["scripted"]["lsjson"] = [_Result(returncode=1, stderr="not found")]
    with pytest.raises(RuntimeError, match="lsjson"):
        gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())


def test_raises_when_drive_returns_no_id_for_a_subfolder(rclone):
    """Fail loudly rather than storing a blank id that would upload to the root."""
    rclone["scripted"]["lsjson"] = [
        _Result(stdout="[]"),
        _Result(stdout=_dirs("logos", "backgrounds")),  # squareart never came back
    ]
    with pytest.raises(RuntimeError, match="squareart"):
        gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())


@pytest.mark.parametrize("bad_id", ["", "   ", None, 12345])
def test_raises_when_drive_returns_a_subfolder_without_a_usable_id(rclone, bad_id):
    """A present NAME with a blank/absent/non-string ID must fail loudly.

    The earlier guard only checked the name was present, so a record like
    {"Name": "logos", "ID": ""} sailed through and produced a routed row with an
    empty folder_id — which _drive_targets skips silently, so that art type would
    simply stop uploading with no error anywhere.
    """
    listing = json.dumps(
        [
            {"Name": "logos", "ID": bad_id},
            {"Name": "backgrounds", "ID": "ID_backgrounds"},
            {"Name": "squareart", "ID": "ID_squareart"},
        ]
    )
    rclone["scripted"]["lsjson"] = [_Result(stdout=listing), _Result(stdout=listing)]
    with pytest.raises(RuntimeError, match="logos"):
        gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())


def test_rejects_an_unsafe_parent_id(rclone):
    with pytest.raises(ValueError):
        gdrive_upload.ensure_type_subfolders("--drive-config=/etc/passwd", _Sync(), _Log())
    assert rclone["calls"] == []  # refused before any rclone ran


def test_raises_without_an_upload_token(monkeypatch, rclone):
    monkeypatch.setattr(gdrive_upload, "_upload_auth_env", lambda cfg: {})
    with pytest.raises(RuntimeError, match="OAuth token"):
        gdrive_upload.ensure_type_subfolders("PARENT", _Sync(), _Log())
