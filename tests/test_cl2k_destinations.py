"""Tests for the CL2K maker's routed save locations and Drive endpoints.

Save locations are two lists — ``local_folders`` and ``gdrive_uploads`` — whose
entries each claim a subset of CL2K_IMAGE_TYPES; every claimer receives a copy
and zero claimers means "not auto-saved" (downloadable only). These exercise
the real fan-out in _persist_poster against a real on-disk SQLite DB + temp
dirs, the Cl2kMakerConfig legacy-field migration (old output_dir /
upload_to_gdrive / destinations first-match routing) on raw dicts, and the
/test-drive + /upload-status handlers directly."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.cl2k.config import (  # noqa: E402
    CL2K_IMAGE_TYPES,
    Cl2kGdriveUpload,
    Cl2kLocalFolder,
    Cl2kMakerConfig,
)
from backend.util.config import ChubConfig  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402
from backend.util.database.cl2k_generated import cl2k_generated_for  # noqa: E402


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
    return Cl2kMakerConfig(**kw)


def _folder(path, types, name="F"):
    return Cl2kLocalFolder(name=name, path=path, types=types)


def _drive(folder_id, types, name="D"):
    return Cl2kGdriveUpload(name=name, folder_id=folder_id, types=types)


PERSIST_ARGS = dict(
    kind="movie",
    tvdb_id=None,
    imdb_id=None,
    season_number=None,
    backdrop_path=None,
    logo_source="",
)


# --- target selection (_local_targets / _drive_targets) ---


def test_local_targets_claim_order_dedup_blanks():
    from backend.modules.cl2k_maker import _local_targets

    cfg = _cfg(
        local_folders=[
            _folder("/a", ["poster", "logo"], name="A"),
            _folder("/b", ["poster"], name="B"),
            _folder("/a", ["poster"], name="A-dup"),  # duplicate path -> one copy
            _folder("   ", ["poster"], name="Blank"),  # blank path skipped
            _folder("/inert", [], name="Inert"),  # empty types claims nothing
        ]
    )
    assert _local_targets(cfg, "poster") == ["/a", "/b"]  # config order
    assert _local_targets(cfg, "logo") == ["/a"]
    assert _local_targets(cfg, "background") == []
    assert _local_targets(_cfg(), "poster") == []


def test_drive_targets_claim_order_dedup_blanks():
    from backend.modules.cl2k_maker import _drive_targets

    cfg = _cfg(
        gdrive_uploads=[
            _drive("F1", ["poster"], name="One"),
            _drive("F2", ["poster", "background"], name="Two"),
            _drive("F1", ["poster"], name="One-dup"),  # duplicate id -> one upload
            _drive("  ", ["poster"], name="Blank"),  # blank id skipped
            _drive("F3", [], name="Inert"),  # empty types claims nothing
        ]
    )
    assert _drive_targets(cfg, "poster") == ["F1", "F2"]  # config order
    assert _drive_targets(cfg, "background") == ["F2"]
    assert _drive_targets(cfg, "squareart") == []
    assert _drive_targets(_cfg(), "poster") == []


# --- _persist_poster: local fan-out ---


def test_persist_writes_every_claiming_folder(db, tmp_path):
    from backend.modules.cl2k_maker import _persist_poster

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_c = tmp_path / "logos-only"
    cfg = _cfg(
        local_folders=[
            _folder(str(dir_a), ["poster"], name="A"),
            _folder(str(dir_b), ["poster"], name="B"),
            _folder(str(dir_c), ["logo"], name="C"),  # doesn't claim posters
        ]
    )
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"poster-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=False,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "generated"
    assert res["saved_local"] is True and res["uploaded"] is False

    files_a = list(dir_a.iterdir())
    files_b = list(dir_b.iterdir())
    assert len(files_a) == 1 and len(files_b) == 1
    assert files_a[0].name == files_b[0].name
    assert files_a[0].read_bytes() == b"poster-bytes"
    assert files_b[0].read_bytes() == b"poster-bytes"
    assert not dir_c.exists()  # non-claiming folder untouched
    assert res["saved_paths"] == [str(files_a[0]), str(files_b[0])]
    assert res["file"] == str(files_a[0])  # first written path

    rows = db.poster.get_all()
    assert len(rows) == 2  # one poster_cache row per copy
    by_file = {r["file"]: r for r in rows}
    assert set(by_file) == {str(files_a[0]), str(files_b[0])}
    for r in rows:
        assert r["image_type"] == "poster"
        assert r["style"] == cfg.style
        assert r["priority"] == cfg.priority
    assert by_file[str(files_a[0])]["folder"] == "a"
    assert by_file[str(files_b[0])]["folder"] == "b"

    # Provenance: exactly one row per generation, keyed on the FIRST copy.
    prov = cl2k_generated_for(db).list_recent()
    assert len(prov) == 1
    assert prov[0]["file"] == str(files_a[0])
    assert prov[0]["uploaded"] == 0


def test_persist_asset_type_skips_provenance(db, tmp_path):
    from backend.modules.cl2k_maker import _persist_poster

    out = tmp_path / "logos"
    cfg = _cfg(local_folders=[_folder(str(out), ["logo"])])
    res = _persist_poster(
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
    assert res["status"] == "generated"
    rows = db.poster.get_all()
    assert len(rows) == 1
    assert rows[0]["image_type"] == "logo"
    assert rows[0]["file"].endswith(" - Logo.png")
    # An asset must not appear in the poster provenance table (exists_for gate).
    assert cl2k_generated_for(db).list_recent() == []


def test_not_routed_is_generated_with_no_writes(db, tmp_path):
    from backend.modules.cl2k_maker import _persist_poster

    only_logos = tmp_path / "logos"
    cfg = _cfg(local_folders=[_folder(str(only_logos), ["logo"])])
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"square-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=None,
        image_type="squareart",
        asset_suffix=" - SquareArt",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "generated"
    assert res["not_routed"] is True
    assert res["saved_local"] is False and res["uploaded"] is False
    assert res["file"] == os.path.basename(res["file"])  # bare filename, no dir
    assert not only_logos.exists()
    assert db.poster.get_all() == []
    assert cl2k_generated_for(db).list_recent() == []


# --- _persist_poster: Drive fan-out ---


def test_upload_fans_out_to_every_claiming_drive(db, tmp_path, monkeypatch):
    from backend.modules.cl2k_maker import _persist_poster

    calls = []
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.upload_file",
        lambda src, folder_id, sync_cfg, logger: calls.append(folder_id),
    )
    out = tmp_path / "out"
    cfg = _cfg(
        local_folders=[_folder(str(out), ["poster"])],
        gdrive_uploads=[
            _drive("F1", ["poster"], name="One"),
            _drive("F2", ["poster"], name="Two"),
            _drive("F3", ["logo"], name="Logos"),  # doesn't claim posters
        ],
    )
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"poster-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=True,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert calls == ["F1", "F2"]  # once per claiming folder id, config order
    assert res["status"] == "generated"
    assert res["uploaded"] is True
    assert res["uploaded_folders"] == ["F1", "F2"]
    assert "upload_error" not in res


def test_upload_gdrive_false_skips_none_uploads(db, tmp_path, monkeypatch):
    from backend.modules.cl2k_maker import _persist_poster

    calls = []
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.upload_file",
        lambda src, folder_id, sync_cfg, logger: calls.append(folder_id),
    )
    out = tmp_path / "out"
    cfg = _cfg(
        local_folders=[_folder(str(out), ["poster"])],
        gdrive_uploads=[_drive("F1", ["poster"])],
    )
    common = dict(
        blob=b"poster-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )

    # Explicit False: no upload even though a Drive claims the type.
    res = _persist_poster(db, cfg, StubLogger(), upload_gdrive=False, **common)
    assert calls == []
    assert res["status"] == "generated"
    assert res["saved_local"] is True and res["uploaded"] is False

    # None (the UI/module default): upload wherever routed.
    res = _persist_poster(db, cfg, StubLogger(), upload_gdrive=None, **common)
    assert calls == ["F1"]
    assert res["uploaded"] is True and res["uploaded_folders"] == ["F1"]


def test_drive_only_upload_stages_temp_copy(db, monkeypatch):
    from backend.modules.cl2k_maker import _persist_poster

    staged = {}

    def fake_upload(src, folder_id, sync_cfg, logger):
        staged["src"] = src
        staged["exists"] = os.path.exists(src)
        with open(src, "rb") as fh:
            staged["bytes"] = fh.read()

    monkeypatch.setattr("backend.util.cl2k.gdrive_upload.upload_file", fake_upload)

    # save_local=True but nothing claims the type locally -> Drive-only save.
    cfg = _cfg(gdrive_uploads=[_drive("F1", ["poster"])])
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"drive-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=None,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert staged["exists"] is True and staged["bytes"] == b"drive-bytes"
    assert os.path.basename(staged["src"]) == res["file"]
    assert not os.path.exists(staged["src"])  # temp staging dir cleaned up
    assert res["status"] == "generated"
    assert res["saved_local"] is False and res["uploaded"] is True
    assert res["file"] == os.path.basename(res["file"])  # filename, not a path
    assert db.poster.get_all() == []  # nothing local for CHUB to match
    prov = cl2k_generated_for(db).list_recent()
    assert len(prov) == 1
    assert prov[0]["file"] == res["file"]  # keyed on the basename
    assert prov[0]["uploaded"] == 1


def test_drive_only_all_uploads_failing_is_error(db, monkeypatch):
    from backend.modules.cl2k_maker import _persist_poster

    def boom(src, folder_id, sync_cfg, logger):
        raise RuntimeError(f"quota for {folder_id}")

    monkeypatch.setattr("backend.util.cl2k.gdrive_upload.upload_file", boom)

    cfg = _cfg(gdrive_uploads=[_drive("F1", ["poster"]), _drive("F2", ["poster"])])
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"x",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=False,
        upload_gdrive=None,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "error"
    assert "F1" in res["reason"] and "F2" in res["reason"]
    assert cl2k_generated_for(db).list_recent() == []


def test_drive_partial_failure_is_generated_with_upload_error(db, monkeypatch):
    from backend.modules.cl2k_maker import _persist_poster

    def flaky(src, folder_id, sync_cfg, logger):
        if folder_id == "BAD":
            raise RuntimeError("quota exceeded")

    monkeypatch.setattr("backend.util.cl2k.gdrive_upload.upload_file", flaky)

    cfg = _cfg(gdrive_uploads=[_drive("BAD", ["poster"]), _drive("GOOD", ["poster"])])
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"x",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=False,
        upload_gdrive=None,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "generated"
    assert res["uploaded"] is True
    assert res["uploaded_folders"] == ["GOOD"]
    assert "BAD" in res["upload_error"]


# --- _persist_poster: local write failures ---


def test_local_write_failure_is_partial(db, tmp_path):
    from backend.modules.cl2k_maker import _persist_poster

    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"i am a regular file")
    bad_dir = blocker / "sub"  # makedirs under a file -> OSError
    good_dir = tmp_path / "good"
    cfg = _cfg(
        local_folders=[
            _folder(str(bad_dir), ["poster"], name="Bad"),
            _folder(str(good_dir), ["poster"], name="Good"),
        ]
    )
    res = _persist_poster(
        db,
        cfg,
        StubLogger(),
        blob=b"poster-bytes",
        title="Foo",
        year=2020,
        tmdb_id=1,
        save_local=True,
        upload_gdrive=False,
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "generated"  # the other folder still got its copy
    assert res["saved_local"] is True
    assert len(res["saved_paths"]) == 1
    assert res["saved_paths"][0].startswith(str(good_dir))
    assert str(bad_dir) in res["save_error"]
    rows = db.poster.get_all()
    assert len(rows) == 1 and rows[0]["file"] == res["saved_paths"][0]


def test_all_locals_failing_with_no_drives_is_error(db, tmp_path):
    from backend.modules.cl2k_maker import _persist_poster

    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"i am a regular file")
    bad_dir = blocker / "sub"
    cfg = _cfg(local_folders=[_folder(str(bad_dir), ["poster"])])
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
        image_type="poster",
        asset_suffix="",
        ext=".jpg",
        **PERSIST_ARGS,
    )
    assert res["status"] == "error"
    assert "local save failed" in res["reason"]
    assert str(bad_dir) in res["reason"]
    assert db.poster.get_all() == []


# --- legacy save-field migration (Cl2kMakerConfig.model_validate on raw dicts) ---


def _mig(raw):
    return Cl2kMakerConfig.model_validate(raw)


def test_migration_simple_legacy_routes_all_types():
    cfg = _mig(
        {"output_dir": "/out", "upload_to_gdrive": True, "gdrive_folder_id": "GID"}
    )
    assert [f.model_dump() for f in cfg.local_folders] == [
        {"name": "Output", "path": "/out", "types": list(CL2K_IMAGE_TYPES)}
    ]
    assert [d.model_dump() for d in cfg.gdrive_uploads] == [
        {"name": "Drive", "folder_id": "GID", "types": list(CL2K_IMAGE_TYPES)}
    ]


def test_migration_upload_off_keeps_folder_id_inert():
    cfg = _mig(
        {"output_dir": "/out", "upload_to_gdrive": False, "gdrive_folder_id": "GID"}
    )
    assert cfg.local_folders[0].types == list(CL2K_IMAGE_TYPES)
    assert len(cfg.gdrive_uploads) == 1
    assert cfg.gdrive_uploads[0].folder_id == "GID"
    assert cfg.gdrive_uploads[0].types == []  # kept, but routes nothing


def test_migration_first_match_and_shadowed_destination():
    cfg = _mig(
        {
            "output_dir": "/out",
            "destinations": [
                {
                    "name": "Assets",
                    "image_types": ["logo", "squareart"],
                    "output_dir": "/assets",
                },
                {"name": "Logos", "image_types": ["logo"], "output_dir": "/logos"},
            ],
        }
    )
    by_path = {f.path: f for f in cfg.local_folders}
    # First destination claiming a type won; later claimers get nothing.
    assert by_path["/assets"].types == ["logo", "squareart"]
    # Types no destination claimed fall back to the top-level output_dir.
    assert by_path["/out"].types == ["poster", "background"]
    # Fully shadowed destination keeps its dir as an inert entry.
    assert by_path["/logos"].types == []
    assert by_path["/logos"].name == "Logos"
    assert [f.path for f in cfg.local_folders] == ["/out", "/assets", "/logos"]
    assert cfg.gdrive_uploads == []


def test_migration_destination_without_dir_falls_back_to_output():
    # Per-field fallback: a destination that names image_types but no output_dir
    # routed those types to the top-level dir under the old logic.
    cfg = _mig(
        {
            "output_dir": "/out",
            "destinations": [{"name": "BG", "image_types": ["background"]}],
        }
    )
    assert [f.model_dump() for f in cfg.local_folders] == [
        {"name": "Output", "path": "/out", "types": list(CL2K_IMAGE_TYPES)}
    ]
    assert cfg.gdrive_uploads == []


def test_migration_additive_upload_prefers_destination_folder():
    # Global upload ON + destination with its own folder_id: that type uploads
    # to the destination's folder, everything else to the global one.
    cfg = _mig(
        {
            "output_dir": "/out",
            "upload_to_gdrive": True,
            "gdrive_folder_id": "GID",
            "destinations": [
                {"name": "P", "image_types": ["poster"], "gdrive_folder_id": "DFID"}
            ],
        }
    )
    by_id = {d.folder_id: d for d in cfg.gdrive_uploads}
    assert by_id["DFID"].types == ["poster"]
    assert by_id["DFID"].name == "P"
    assert by_id["GID"].types == ["logo", "background", "squareart"]


def test_migration_destination_upload_flag_without_global():
    # Upload was additive: a destination's own upload_to_gdrive switched its
    # types on even with the global switch off (falling back to the global id).
    cfg = _mig(
        {
            "output_dir": "/out",
            "upload_to_gdrive": False,
            "gdrive_folder_id": "GID",
            "destinations": [
                {"name": "P", "image_types": ["poster"], "upload_to_gdrive": True}
            ],
        }
    )
    assert [d.model_dump() for d in cfg.gdrive_uploads] == [
        {"name": "Drive", "folder_id": "GID", "types": ["poster"]}
    ]


def test_migration_is_idempotent():
    raw = {
        "output_dir": "/out",
        "upload_to_gdrive": True,
        "gdrive_folder_id": "GID",
        "destinations": [
            {"name": "Assets", "image_types": ["logo"], "output_dir": "/assets"}
        ],
    }
    once = _mig(raw)
    twice = Cl2kMakerConfig.model_validate(once.model_dump())
    assert twice == once
    assert twice.local_folders == once.local_folders
    assert twice.gdrive_uploads == once.gdrive_uploads


def test_migration_never_resurrects_deleted_entries():
    # New-shape list present + stale legacy keys: legacy must be ignored, so a
    # location the user deleted post-redesign can't reappear.
    cfg = _mig(
        {
            "local_folders": [{"name": "Keep", "path": "/keep", "types": ["poster"]}],
            "output_dir": "/old",
            "upload_to_gdrive": True,
            "gdrive_folder_id": "GID",
        }
    )
    assert [f.path for f in cfg.local_folders] == ["/keep"]
    assert cfg.gdrive_uploads == []


def test_new_shape_passes_through_untouched():
    raw = {
        "local_folders": [{"name": "A", "path": "/a", "types": ["poster"]}],
        "gdrive_uploads": [{"name": "D", "folder_id": "F1", "types": ["logo"]}],
    }
    cfg = _mig(raw)
    assert [f.model_dump() for f in cfg.local_folders] == raw["local_folders"]
    assert [d.model_dump() for d in cfg.gdrive_uploads] == raw["gdrive_uploads"]
    # A fresh config with no save fields at all stays empty.
    empty = _mig({})
    assert empty.local_folders == [] and empty.gdrive_uploads == []


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
        lambda folder_id, sync_cfg, logger: (
            "Uploaded and removed a test file — upload works."
        ),
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


# --- /api/cl2k-maker/upload-status (handler called directly) ---


def _upload_status_data(monkeypatch, cl2k_kwargs, token_ok=True):
    from backend.api import cl2k_maker as api

    cfg = ChubConfig(cl2k_maker=Cl2kMakerConfig(**cl2k_kwargs))
    seen = {}

    def fake_token(sync_cfg):
        seen["sync_cfg"] = sync_cfg
        return token_ok

    monkeypatch.setattr(api, "load_config", lambda: cfg)
    monkeypatch.setattr("backend.util.cl2k.gdrive_upload.has_upload_token", fake_token)
    resp = api.upload_status(db=None, logger=StubLogger())
    assert resp.status_code == 200
    assert seen["sync_cfg"] is cfg.sync_gdrive
    return json.loads(resp.body)["data"]


def test_upload_status_configured_requires_types(monkeypatch):
    data = _upload_status_data(
        monkeypatch,
        dict(
            local_folders=[_folder("/x", ["poster"])],
            gdrive_uploads=[_drive("GID", [])],  # id set but no claimed types
        ),
    )
    assert data["local_configured"] is True
    assert data["gdrive_configured"] is False  # inert entry doesn't count
    assert data["token_ok"] is True


def test_upload_status_blank_path_and_token_passthrough(monkeypatch):
    data = _upload_status_data(
        monkeypatch,
        dict(
            local_folders=[_folder("   ", ["poster"])],  # blank path doesn't count
            gdrive_uploads=[_drive("GID", ["logo"])],
        ),
        token_ok=False,
    )
    assert data["local_configured"] is False
    assert data["gdrive_configured"] is True
    assert data["token_ok"] is False
