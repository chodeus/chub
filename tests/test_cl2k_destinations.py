"""Tests for CL2K maker optional per-image-type destination routing and the
Drive upload test endpoint.

Routing sends each generated file to the destination whose image_types match
(local dir + Drive folder), falling back to the single default fields when no
destination matches. These exercise the real routing in _persist_poster against
a real on-disk SQLite DB + temp dirs, and the /test-drive handler directly."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.cl2k.config import Cl2kDestination, Cl2kMakerConfig  # noqa: E402
from backend.util.config import ChubConfig  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    d.__enter__()
    d._ensure_schema_initialized()
    yield d
    try:
        d.__exit__(None, None, None)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _cfg(**kw):
    base = dict(output_dir="", gdrive_folder_id="", upload_to_gdrive=False)
    base.update(kw)
    return Cl2kMakerConfig(**base)


PERSIST_ARGS = dict(
    kind="movie",
    tvdb_id=None,
    imdb_id=None,
    season_number=None,
    backdrop_path=None,
    logo_source="",
)


def test_match_destination():
    from backend.modules.cl2k_maker import _match_destination

    cfg = _cfg(
        destinations=[
            Cl2kDestination(
                name="Assets",
                image_types=["logo", "background", "squareart"],
                output_dir="/assets",
            ),
            Cl2kDestination(name="Posters", image_types=["poster"], output_dir="/posters"),
        ]
    )
    assert _match_destination(cfg, "logo").name == "Assets"
    assert _match_destination(cfg, "background").name == "Assets"
    assert _match_destination(cfg, "poster").name == "Posters"
    # Unknown / uncovered type and no-destinations both fall through to default.
    assert _match_destination(cfg, "banner") is None
    assert _match_destination(_cfg(), "logo") is None


def test_persist_routes_local_by_type(db, tmp_path):
    from backend.modules.cl2k_maker import _persist_poster

    default_dir = tmp_path / "default"
    assets_dir = tmp_path / "assets"
    cfg = _cfg(
        output_dir=str(default_dir),
        destinations=[
            Cl2kDestination(name="Assets", image_types=["logo"], output_dir=str(assets_dir)),
        ],
    )

    # logo matches the Assets destination -> assets_dir
    _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"logo-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=False,
        image_type="logo",
        asset_suffix=" - Logo",
        ext=".png",
        **PERSIST_ARGS,
    )
    # squareart is NOT covered by any destination -> default_dir
    _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"square-bytes",
        title="Bar",
        year=2021,
        tmdb_id=2,
        save_local=True,
        upload_gdrive=False,
        image_type="squareart",
        asset_suffix=" - SquareArt",
        ext=".jpg",
        **PERSIST_ARGS,
    )

    assets_files = list(assets_dir.iterdir()) if assets_dir.exists() else []
    default_files = list(default_dir.iterdir()) if default_dir.exists() else []
    assert len(assets_files) == 1 and assets_files[0].suffix == ".png"
    assert len(default_files) == 1 and default_files[0].suffix == ".jpg"


def test_persist_routes_upload_folder_by_type(db, tmp_path, monkeypatch):
    from backend.modules.cl2k_maker import _persist_poster

    captured = {}

    def fake_upload(src, folder_id, sync_cfg, logger):
        captured["folder_id"] = folder_id

    monkeypatch.setattr("backend.util.cl2k.gdrive_upload.upload_file", fake_upload)

    cfg = _cfg(
        output_dir=str(tmp_path),
        gdrive_folder_id="DEFAULTFOLDER",
        upload_to_gdrive=True,
        destinations=[
            Cl2kDestination(
                name="Assets",
                image_types=["logo"],
                upload_to_gdrive=True,
                gdrive_folder_id="ASSETSFOLDER",
            ),
        ],
    )

    # Drive-only save (no local) so only the upload path runs; logo -> ASSETSFOLDER.
    _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"logo-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=False,
        upload_gdrive=True,
        image_type="logo",
        asset_suffix=" - Logo",
        ext=".png",
        **PERSIST_ARGS,
    )
    assert captured["folder_id"] == "ASSETSFOLDER"

    # A poster is uncovered -> falls back to the default folder.
    captured.clear()
    _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"poster-bytes",
        title="Bar",
        year=2021,
        tmdb_id=2,
        save_local=False,
        upload_gdrive=True,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert captured["folder_id"] == "DEFAULTFOLDER"


# --- /api/cl2k-maker/test-drive (handler called directly) ---


def test_endpoint_requires_folder_id():
    from backend.api import cl2k_maker as api

    resp = api.test_drive(
        api.TestDriveRequest(gdrive_folder_id="  "), db=None, logger=StubLogger()
    )
    assert resp.status_code == 400
    assert json.loads(resp.body)["error_code"] == "GDRIVE_FOLDER_REQUIRED"


def test_endpoint_no_token_is_400(monkeypatch):
    from backend.api import cl2k_maker as api

    # Default config carries no OAuth token -> config precondition, not 502.
    monkeypatch.setattr(api, "load_config", lambda: ChubConfig())
    resp = api.test_drive(
        api.TestDriveRequest(gdrive_folder_id="ABC123"), db=None, logger=StubLogger()
    )
    assert resp.status_code == 400
    assert json.loads(resp.body)["error_code"] == "GDRIVE_NO_TOKEN"


def test_endpoint_success(monkeypatch):
    from backend.api import cl2k_maker as api

    monkeypatch.setattr(api, "load_config", lambda: ChubConfig())
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.has_upload_token", lambda sync_cfg: True
    )
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.test_drive_access",
        lambda folder_id, sync_cfg, logger: "Uploaded and removed a test file — upload works.",
    )
    resp = api.test_drive(
        api.TestDriveRequest(gdrive_folder_id="ABC123"), db=None, logger=StubLogger()
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["success"] is True
    assert "upload works" in body["message"].lower()
    assert body["data"]["folder_id"] == "ABC123"


def test_endpoint_failure_maps_to_502(monkeypatch):
    from backend.api import cl2k_maker as api

    def boom(folder_id, sync_cfg, logger):
        raise RuntimeError("rclone copy failed: googleapi: Error 404")

    monkeypatch.setattr(api, "load_config", lambda: ChubConfig())
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.has_upload_token", lambda sync_cfg: True
    )
    monkeypatch.setattr("backend.util.cl2k.gdrive_upload.test_drive_access", boom)
    resp = api.test_drive(
        api.TestDriveRequest(gdrive_folder_id="ABC123"), db=None, logger=StubLogger()
    )
    assert resp.status_code == 502
    assert json.loads(resp.body)["error_code"] == "GDRIVE_TEST_FAILED"


def test_has_local_output():
    from backend.modules.cl2k_maker import _has_local_output

    assert _has_local_output(_cfg(output_dir="/x")) is True
    assert (
        _has_local_output(
            _cfg(
                output_dir="",
                destinations=[Cl2kDestination(name="A", image_types=["logo"], output_dir="/y")],
            )
        )
        is True
    )
    assert _has_local_output(_cfg(output_dir="")) is False


def test_additive_upload_inherits_global(db, tmp_path, monkeypatch):
    """A destination created only to redirect the local dir (upload unchecked)
    must NOT disable Drive upload when the global switch is on."""
    from backend.modules.cl2k_maker import _persist_poster

    captured = {}
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.upload_file",
        lambda src, folder_id, sync_cfg, logger: captured.__setitem__("folder_id", folder_id),
    )

    cfg = _cfg(
        gdrive_folder_id="GLOBALFOLDER",
        upload_to_gdrive=True,  # global upload ON
        destinations=[
            # A destination that redirects logos but leaves upload at its False
            # default must NOT turn the (global) upload off for logos.
            Cl2kDestination(name="Assets", image_types=["logo"]),
        ],
    )
    # Drive-only + upload_gdrive=None (the UI/batch default) must still upload.
    _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"logo",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=False,
        upload_gdrive=None,
        image_type="logo",
        asset_suffix=" - Logo",
        ext=".png",
        **PERSIST_ARGS,
    )
    assert captured.get("folder_id") == "GLOBALFOLDER"


def test_persist_errors_when_no_output_dir(db):
    """Uncovered type + blank global output_dir returns a clean error, not a crash."""
    from backend.modules.cl2k_maker import _persist_poster

    cfg = _cfg(
        output_dir="",
        destinations=[Cl2kDestination(name="A", image_types=["logo"], output_dir="/tmp/a")],
    )
    # squareart is not covered by any destination and global is blank.
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"x",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=False,
        image_type="squareart",
        asset_suffix=" - SquareArt",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "error"
    assert "output directory" in res["reason"].lower()
