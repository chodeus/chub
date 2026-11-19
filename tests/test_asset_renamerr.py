"""Tests for backend/modules/asset_renamerr.py and the shared asset plumbing.

Covers:
* build_asset_record() image_type detection + suffix stripping (incl. the real
  g-drive filename convention and negative cases).
* image_type filtering keeps poster matching isolated from asset rows.
* source-priority resolution (local vs fanart, first match wins).
* the apply dispatcher (banner skipped on the direct path; correct PlexClient
  method called otherwise) and the Kometa rename path.
"""

import errno
import os
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from backend.modules.asset_moves import AssetMoves
from backend.modules.asset_renamerr import (
    AssetRenamerr,
    apply_capability,
)
from backend.modules.poster_renamerr import PosterRenamerr, build_asset_record
from backend.util.constants import asset_type_regex
from backend.util.database import ChubDB


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _empty_index_db(rows=None):
    """A stand-in db whose plex_media_cache has no rows for any instance, so
    PlexMediaIndex is unavailable and _resolve_apply_targets uses the live
    type-filtered fallback (the path these direct-apply tests exercise)."""
    return SimpleNamespace(
        plex=SimpleNamespace(get_by_instance=lambda name: rows or [])
    )


def make_module(**config_overrides):
    """Build an AssetRenamerr without triggering ChubModule.__init__/config load."""
    m = object.__new__(AssetRenamerr)
    m.logger = _logger()
    m._cancel_event = None
    m._plex_clients = {}
    cfg = {
        "log_level": "info",
        "dry_run": False,
        "sources": ["local", "fanart"],
        "asset_types": ["logo", "squareart", "background", "banner"],
        "apply_method": "kometa",
        "action_type": "copy",
        "asset_folders": False,
        "destination_dir": "",
        "source_dirs": [],
        "print_only_renames": False,
        "sync_assets": False,
        "tmdb_language": "en",
        "instances": [],
        "plex_scope": [],
    }
    cfg.update(config_overrides)
    m.config = SimpleNamespace(**cfg)
    m.full_config = SimpleNamespace(
        tmdb=SimpleNamespace(apikey="", cache_expiration=60),
        fanart=SimpleNamespace(client_key="", cache_expiration=2),
        instances=SimpleNamespace(plex={}),
    )
    return m


@pytest.fixture
def db(tmp_path):
    logger = _logger()
    path = str(tmp_path / "chub.db")
    with ChubDB(logger, db_path=path) as database:
        yield database


# --------------------------------------------------------------------------
# build_asset_record — image_type detection + suffix stripping
# --------------------------------------------------------------------------


def test_real_gdrive_movie_logo():
    rec = build_asset_record(
        "8 A.M. Metro (2023) {tmdb-1121330} {imdb-tt27511275} - Logo.png", "/x"
    )
    assert rec["image_type"] == "logo"
    assert rec["title"] == "8 A.M. Metro"
    assert rec["year"] == 2023
    assert rec["tmdb_id"] == 1121330
    assert rec["imdb_id"] == "tt27511275"
    assert rec["normalized_title"] == "8ammetro"


def test_real_gdrive_collection_logo():
    rec = build_asset_record(
        "De De Pyaar De Collection {tmdb-1511685} - Logo.png", "/x"
    )
    assert rec["image_type"] == "logo"
    assert rec["tmdb_id"] == 1511685
    assert rec["year"] is None
    # year-less + Collection suffix classifies as a collection
    assert AssetRenamerr._classify(rec) == "collection"


def test_year_less_asset_with_imdb_id_is_movie():
    """Mirrors poster_renamerr: an IMDb id vetoes the year-less collection
    branch, so a real drive file like "Leo 2 {tmdb-…} {imdb-tt…} - Logo.png"
    stays matchable against the movie."""
    rec = build_asset_record(
        "Leo 2 {tmdb-1235976} {imdb-tt31066554} - Logo.png", "/x"
    )
    assert rec["year"] is None
    assert rec["imdb_id"] == "tt31066554"
    assert AssetRenamerr._classify(rec) == "movie"


@pytest.mark.parametrize(
    "fname,expected",
    [
        ("Movie (1999) - Logo.png", "logo"),
        ("Movie (1999)_Logo.png", "logo"),
        ("Movie (1999) - SquareArt.png", "squareart"),
        ("Movie (1999) - Background.png", "background"),
        ("Movie (1999) - Banner.png", "banner"),
        ("Movie (1999).png", "poster"),  # no suffix -> poster
    ],
)
def test_suffix_variants(fname, expected):
    rec = build_asset_record(fname, "/x")
    assert rec["image_type"] == expected


def test_negative_title_not_eaten():
    """A movie literally containing the word in its title is NOT an asset tag."""
    rec = build_asset_record("Open Season 2 (2008) - Logo.png", "/x")
    # the " - Logo" tag is stripped; "Open Season 2" survives as the title
    assert rec["image_type"] == "logo"
    assert "Open Season 2" in rec["title"]
    # and a bare title without a delimited tag isn't mistaken for an asset
    bare = build_asset_record("Background Noise (2010).png", "/x")
    assert bare["image_type"] == "poster"


def test_asset_and_poster_share_match_key():
    """The logo and the poster for the same film must normalize to one key."""
    poster = build_asset_record("8 A.M. Metro (2023) {tmdb-1121330}.png", "/x")
    logo = build_asset_record("8 A.M. Metro (2023) {tmdb-1121330} - Logo.png", "/x")
    assert poster["normalized_title"] == logo["normalized_title"]
    assert poster["image_type"] == "poster" and logo["image_type"] == "logo"


def test_asset_type_regex_requires_delimiter():
    assert asset_type_regex.search("Logo (2017)") is None
    assert asset_type_regex.search("Show - Logo").group(1).lower() == "logo"


# --------------------------------------------------------------------------
# image_type isolation: poster matching ignores asset rows
# --------------------------------------------------------------------------


def _media(**over):
    base = {
        "id": 1,
        "asset_type": "movie",
        "title": "8 A.M. Metro",
        "normalized_title": "8ammetro",
        "year": 2023,
        "tmdb_id": 1121330,
        "tvdb_id": None,
        "imdb_id": "tt27511275",
        "season_number": None,
        "alternate_titles": "[]",
        "instance_name": "radarr1",
        "library_name": None,
        "folder": "8 A.M. Metro (2023)",
    }
    base.update(over)
    return base


def _seed(db, image_type, fname, folder="/x", priority=0):
    db.poster.upsert(
        {
            "asset_type": "movie",
            "title": "8 A.M. Metro",
            "normalized_title": "8ammetro",
            "year": 2023,
            "tmdb_id": 1121330,
            "tvdb_id": None,
            "imdb_id": "tt27511275",
            "season_number": None,
            "folder": "x",
            "file": f"{folder}/{fname}",
            "style": None,
            "priority": priority,
            "image_type": image_type,
        }
    )


def test_poster_match_ignores_logo_rows(db):
    _seed(db, "poster", "8 A.M. Metro (2023).png")
    _seed(db, "logo", "8 A.M. Metro (2023) - Logo.png")
    poster = PosterRenamerr.find_asset_candidate(_media(), db, image_type="poster")
    logo = PosterRenamerr.find_asset_candidate(_media(), db, image_type="logo")
    assert poster["matched"] and poster["candidate"]["image_type"] == "poster"
    assert logo["matched"] and logo["candidate"]["image_type"] == "logo"


def test_find_asset_candidate_reused_conn_matches(db):
    """Option A: resolving via a reused read connection yields the SAME
    candidate as the default connect-per-query path — both the ID path and the
    no-id prefix path."""
    _seed(db, "logo", "8 A.M. Metro (2023) - Logo.png")  # ID-matched
    base = PosterRenamerr.find_asset_candidate(_media(), db, image_type="logo")
    conn = db.poster.open_read_connection()
    try:
        reused = PosterRenamerr.find_asset_candidate(
            _media(), db, image_type="logo", conn=conn
        )
        # No-id media exercises the prefix path on the same reused connection.
        noid = _media(tmdb_id=None, tvdb_id=None, imdb_id=None)
        reused_prefix = PosterRenamerr.find_asset_candidate(
            noid, db, image_type="logo", conn=conn
        )
    finally:
        conn.close()
    assert reused["matched"]
    assert reused["candidate"]["file"] == base["candidate"]["file"]
    assert reused_prefix["candidate"]["file"] == base["candidate"]["file"]


def test_open_read_connection_is_read_only(db):
    """The reused connection enforces query_only — it can read but never write,
    so it can't corrupt the cache or hold a write transaction open."""
    conn = db.poster.open_read_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM poster_cache").fetchone() is not None
        with pytest.raises(
            sqlite3.OperationalError, match="^attempt to write a readonly database$"
        ):
            conn.execute(
                "INSERT INTO poster_cache (asset_type, file) VALUES ('movie', '/x/y')"
            )
    finally:
        conn.close()


# --------------------------------------------------------------------------
# source priority resolution
# --------------------------------------------------------------------------


def _fake_fanart(url="https://assets.fanart.tv/fanart/movies/123/hdmovielogo/l.png"):
    return SimpleNamespace(get_images=lambda *a, **k: {"logo": url, "background": None})


def test_source_priority_local_first(db, tmp_path):
    logo = tmp_path / "8 A.M. Metro (2023) - Logo.png"
    logo.write_bytes(b"png")
    _seed(db, "logo", logo.name, folder=str(tmp_path))
    m = make_module(sources=["local", "fanart"])
    assert m._resolve_source(_media(), db, "logo", False, _fake_fanart()) == ("local", str(logo), None)


def test_local_source_falls_back_when_the_winner_file_is_gone(db, tmp_path):
    """A cached row whose source root is gone yields to the next match still on disk."""
    logo = tmp_path / "8 A.M. Metro (2023) - Logo.png"
    logo.write_bytes(b"png")
    _seed(db, "logo", logo.name, folder=str(tmp_path), priority=0)
    _seed(db, "logo", logo.name, folder=str(tmp_path / "unmounted"), priority=1)
    m = make_module(sources=["local"])
    resolved = m._resolve_source(_media(), db, "logo", False, None)
    assert resolved == ("local", str(logo), None)


def test_local_source_skips_a_title_match_ranked_below_a_gone_id_hit(db, tmp_path):
    """The id hit outranks the title logo, so with its drive gone fanart is next."""
    logo = tmp_path / "8 A.M. Metro (2023) - Logo.png"
    logo.write_bytes(b"png")
    _seed(db, "logo", logo.name, folder=str(tmp_path), priority=0)
    db.poster.execute_query("UPDATE poster_cache SET tmdb_id=NULL, imdb_id=NULL")
    _seed(
        db,
        "logo",
        "8 A.M. Metro (2023) {tmdb-1121330} - Logo.png",
        folder=str(tmp_path / "unmounted"),
        priority=1,
    )
    m = make_module(sources=["local", "fanart"])
    src, file, url = m._resolve_source(_media(), db, "logo", False, _fake_fanart())
    assert (src, file) == ("fanart", None) and url


def test_source_priority_fanart_first(db):
    _seed(db, "logo", "8 A.M. Metro (2023) - Logo.png")
    m = make_module(sources=["fanart", "local"])
    src, file, url = m._resolve_source(_media(), db, "logo", False, _fake_fanart())
    assert src == "fanart" and url and file is None


def test_source_fallback_to_fanart_when_no_local(db):
    # no local row seeded
    m = make_module(sources=["local", "fanart"])
    resolved = m._resolve_source(_media(), db, "logo", False, _fake_fanart())
    assert resolved is not None
    src, file, url = resolved
    assert src == "fanart" and url


def test_source_none_when_nothing_available(db):
    m = make_module(sources=["local", "fanart"])
    # fanart returns no logo, no local row
    empty_fanart = SimpleNamespace(get_images=lambda *a, **k: {"logo": None})
    assert m._resolve_source(_media(), db, "logo", False, empty_fanart) is None


def test_squareart_never_from_fanart(db):
    # fanart has no square-art type → squareart must not resolve via fanart even
    # when fanart would return a logo/background for the item.
    m = make_module(sources=["fanart", "local"])
    assert m._resolve_source(_media(), db, "squareart", False, _fake_fanart()) is None


# --------------------------------------------------------------------------
# apply dispatcher
# --------------------------------------------------------------------------


def test_direct_banner_skipped():
    m = make_module(apply_method="plex")
    applied, reason, applied_libs = m._apply_direct(
        _empty_index_db(), _media(), "banner", "/x/l.png", None, False
    )
    assert applied is False
    assert "banner" in reason.lower()
    assert applied_libs == []


def test_direct_logo_calls_upload_logo(monkeypatch):
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Movies"], add_posters=True
            )
        ],
    )
    calls = []

    class FakeClient:
        def upload_logo(self, library_name, item_title, **kw):
            calls.append((library_name, item_title, kw.get("url"), kw.get("filepath")))
            return True

    m._plex_clients = {"plex1": FakeClient()}
    applied, detail, applied_libs = m._apply_direct(
        _empty_index_db(), _media(), "logo", None, "http://x/l.png", is_collection=False
    )
    assert applied is True
    assert calls and calls[0][0] == "Movies" and calls[0][2] == "http://x/l.png"
    assert applied_libs == ["plex1/Movies"]


def test_direct_squareart_and_background_methods(monkeypatch):
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Movies"], add_posters=True
            )
        ],
    )
    used = []

    class FakeClient:
        def upload_square_art(self, *a, **k):
            used.append("squareart")
            return True

        def upload_art(self, *a, **k):
            used.append("background")
            return True

    m._plex_clients = {"plex1": FakeClient()}
    m._apply_direct(_empty_index_db(), _media(), "squareart", "/x/s.png", None, False)
    m._apply_direct(_empty_index_db(), _media(), "background", "/x/b.png", None, False)
    assert used == ["squareart", "background"]


# --------------------------------------------------------------------------
# Kometa rename path
# --------------------------------------------------------------------------


def _make_src(tmp_path, name="src.png"):
    p = tmp_path / name
    p.write_bytes(b"img")
    return str(p)


def test_kometa_flat_naming(tmp_path):
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa",
        action_type="copy",
        asset_folders=False,
        destination_dir=str(dest),
    )
    applied, path = m._apply_kometa(_media(), "logo", "local", src, None)
    assert applied
    assert os.path.basename(path) == "8 A.M. Metro (2023)_logo.png"
    assert os.path.exists(path)


def test_kometa_flat_naming_blocks_path_traversal(tmp_path):
    """When a media row has no folder, _kometa_folder falls back to the title;
    with asset_folders off that string is spliced straight into the filename
    under dest_root. A title carrying path separators must be caught by the
    final-path containment guard, not silently written outside destination_dir."""
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa",
        action_type="copy",
        asset_folders=False,
        destination_dir=str(dest),
    )
    evil = _media(folder=None, title="../evil")
    applied, reason = m._apply_kometa(evil, "logo", "local", src, None)
    assert applied is False
    assert "traversal" in reason.lower()
    # Nothing escaped into the parent of destination_dir.
    assert not (tmp_path / "evil (2023)_logo.png").exists()


def test_kometa_asset_folder_linked_outside_the_destination_is_blocked(tmp_path):
    dest = tmp_path / "assets"
    outside = tmp_path / "outside"
    dest.mkdir()
    outside.mkdir()
    (dest / "Metro").symlink_to(outside, target_is_directory=True)
    src = _make_src(tmp_path)
    m = make_module(apply_method="kometa", action_type="copy", asset_folders=True, destination_dir=str(dest))
    applied, reason = m._apply_kometa(_media(folder="Metro"), "logo", "local", src, None)
    assert (applied, "traversal" in reason.lower(), list(outside.iterdir())) == (False, True, [])


def test_apply_chosen_asset_copies_and_locks(tmp_path, db):
    """The manual artwork picker's backend: apply_chosen_asset copies the chosen
    file (kometa path), records an 'applied' provenance row, and sets the
    user_confirmed lock so a re-run reuses it."""
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa",
        action_type="copy",
        asset_folders=False,
        destination_dir=str(dest),
    )
    media = _media(id=42)
    applied, detail = m.apply_chosen_asset(db, "media", media, "logo", src)
    assert applied
    assert os.path.exists(detail)  # file copied to the kometa destination

    row = db.media_asset_matches.get_one("media", 42, "logo")
    assert row["match_status"] == "applied"
    assert row["matched_file"] == src
    assert row["source"] == "local"
    assert row["user_confirmed"] == 1  # locked against future auto-runs


def test_apply_chosen_asset_locks_even_when_apply_fails(tmp_path, db):
    """If the apply leg fails (here: no destination_dir), the chosen file is
    still saved and locked so the next run reuses it rather than re-resolving."""
    src = _make_src(tmp_path)
    m = make_module(apply_method="kometa", destination_dir="")  # forces failure
    media = _media(id=43)
    applied, detail = m.apply_chosen_asset(db, "media", media, "background", src)
    assert not applied

    row = db.media_asset_matches.get_one("media", 43, "background")
    assert row["match_status"] == "failed"
    assert row["matched_file"] == src
    assert row["user_confirmed"] == 1


def test_kometa_asset_folders_naming(tmp_path):
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa",
        action_type="copy",
        asset_folders=True,
        destination_dir=str(dest),
    )
    applied, path = m._apply_kometa(_media(), "background", "local", src, None)
    assert applied
    assert path.endswith(os.path.join("8 A.M. Metro (2023)", "background.png"))
    assert os.path.exists(path)


def test_kometa_dry_run_writes_nothing(tmp_path):
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa",
        asset_folders=False,
        destination_dir=str(dest),
        dry_run=True,
    )
    applied, path = m._apply_kometa(_media(), "logo", "local", src, None)
    assert applied
    assert not os.path.exists(path)  # dry-run wrote nothing


@pytest.mark.parametrize("action", ["copy", "move", "hardlink", "symlink"])
def test_kometa_action_types(tmp_path, action):
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path, name=f"{action}.png")
    m = make_module(
        apply_method="kometa",
        action_type=action,
        asset_folders=True,
        destination_dir=str(dest),
    )
    applied, path = m._apply_kometa(_media(), "logo", "local", src, None)
    assert applied and os.path.exists(path)


def test_a_move_of_an_asset_already_at_its_destination_keeps_it(tmp_path):
    """A destination also listed in source_dirs rescans each placed file as its own source."""
    dest = tmp_path / "assets"
    dest.mkdir()
    copy = make_module(action_type="copy", asset_folders=True, destination_dir=str(dest))
    _applied, placed = copy._apply_kometa(_media(), "logo", "local", _make_src(tmp_path), None)
    move = make_module(action_type="move", asset_folders=True, destination_dir=str(dest))
    applied, path = move._apply_kometa(_media(), "logo", "local", placed, None)
    with open(placed, "rb") as f:
        kept = f.read()
    assert (applied, path, kept) == (True, placed, b"img")


def test_kometa_requires_destination():
    m = make_module(apply_method="kometa", destination_dir="")
    applied, reason = m._apply_kometa(_media(), "logo", "local", "/x/l.png", None)
    assert applied is False and "destination" in reason.lower()


_SKIP_AS_ROOT = pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")


def _standalone_run(db, monkeypatch, tmp_path, dest, **over):
    """A real run(): scans a real logo and matches a seeded movie; only the *arr/Plex sync is stubbed."""
    from backend.modules import asset_renamerr as asset_mod
    from tests.conftest import StubLogger

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "Dune (2021) {tmdb-438631} - Logo.png").write_bytes(b"png")
    db.media.upsert(
        {
            "title": "Dune",
            "normalized_title": "dune",
            "alternate_titles": "[]",
            "year": 2021,
            "tmdb_id": 438631,
            "folder": "Dune (2021)",
            "status": "released",
            "has_content": 1,
        },
        "movie",
        "radarr",
        "radarr1",
    )

    class _OpenDB:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    sync = SimpleNamespace(
        update_arr_database=lambda: None, update_collections_database=lambda: None
    )
    monkeypatch.setattr(asset_mod, "ChubDB", _OpenDB)
    monkeypatch.setattr(asset_mod, "Connector", lambda **k: sync)
    monkeypatch.setattr(
        asset_mod,
        "NotificationManager",
        lambda *a, **k: SimpleNamespace(send_notification=lambda *a, **k: None),
    )
    m = make_module(
        sources=["local"],
        asset_types=["logo"],
        source_dirs=[str(src_dir)],
        destination_dir=str(dest),
        instances=["radarr1"],
        **over,
    )
    m.logger = StubLogger()
    return m


def test_run_applies_a_scanned_logo_to_the_destination(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    m.run()
    assert [p.name for p in dest.iterdir()] == ["Dune (2021)_logo.png"]
    assert m.logger.messages["error"] == []
    assert db.media_asset_matches.get_one("media", 1, "logo")["match_status"] == "applied"


@_SKIP_AS_ROOT
def test_run_fails_once_on_a_destination_it_cannot_write(db, monkeypatch, tmp_path):
    """One error and a failed run, before the *arr sync and with no per-asset warning."""
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    connected = []
    sync = SimpleNamespace(
        update_arr_database=lambda: None, update_collections_database=lambda: None
    )
    monkeypatch.setattr(
        "backend.modules.asset_renamerr.Connector",
        lambda **k: connected.append(k) or sync,
    )
    dest.chmod(0o555)
    try:
        with pytest.raises(PermissionError) as raised:
            m.run()
        st = os.stat(dest)
    finally:
        dest.chmod(0o755)
    assert str(raised.value) == (
        f"[Errno 13] Cannot create files in {dest}: Permission denied (CHUB runs as "
        f"{os.getuid()}:{os.getgid()}; the folder is owned by {st.st_uid}:{st.st_gid}, "
        "dr-xr-xr-x). Check the volume's host path, and that the folder's owner "
        "matches PUID/PGID."
    )
    assert m.logger.messages["warning"] == []
    assert m.logger.messages["error"] == ["\n\nAn error occurred:\n"]
    assert db.media_asset_matches.get_one("media", 1, "logo") is None
    assert connected == [], "the refusal must stop the run before the *arr sync"


@_SKIP_AS_ROOT
def test_dry_run_ignores_an_asset_destination_it_cannot_write(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, dry_run=True)
    dest.chmod(0o555)
    try:
        m.run()
    finally:
        dest.chmod(0o755)
    assert m.logger.messages["error"] == []
    assert list(dest.iterdir()) == []


def _add_arrival(db, tmp_path):
    (tmp_path / "src" / "Arrival (2016) {tmdb-329865} - Logo.png").write_bytes(b"png")
    db.media.upsert(
        {
            "title": "Arrival",
            "normalized_title": "arrival",
            "alternate_titles": "[]",
            "year": 2016,
            "tmdb_id": 329865,
            "folder": "Arrival (2016)",
            "status": "released",
            "has_content": 1,
        },
        "movie",
        "radarr",
        "radarr1",
    )


_OWNER_HINT = "Check the volume's host path, and that the folder's owner matches PUID/PGID."


@_SKIP_AS_ROOT
def test_title_folders_refusing_every_logo_log_once_and_fail_the_run(db, monkeypatch, tmp_path):
    from backend.modules.asset_renamerr import NoAssetWritten
    from backend.util.public_error import failure_text

    dest = tmp_path / "kometa"
    m = _standalone_run(db, monkeypatch, tmp_path, dest, asset_folders=True)
    _add_arrival(db, tmp_path)
    locked = [dest / "Dune (2021)", dest / "Arrival (2016)"]
    for folder in locked:
        folder.mkdir(parents=True)
        folder.chmod(0o555)
    try:
        with pytest.raises(NoAssetWritten) as raised:
            m.run()
    finally:
        for folder in locked:
            folder.chmod(0o755)
    assert str(raised.value) == "All 2 asset(s) asset renamerr tried were refused by their destination"
    assert failure_text("Module asset_renamerr", raised.value) == (
        "Module asset_renamerr failed: permission denied — see the server log"
    )
    assert m.logger.messages["warning"] == []
    assert m.logger.messages["error"] == [
        f"Cannot write {dest}/Dune (2021)/logo.png: Permission denied. {_OWNER_HINT} "
        "2 asset(s) failed this way.",
        "\n\nAn error occurred:\n",
    ]


@_SKIP_AS_ROOT
def test_one_refused_title_folder_is_logged_once_and_the_rest_still_apply(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    m = _standalone_run(db, monkeypatch, tmp_path, dest, asset_folders=True)
    _add_arrival(db, tmp_path)
    locked = dest / "Dune (2021)"
    locked.mkdir(parents=True)
    locked.chmod(0o555)
    try:
        m.run()
    finally:
        locked.chmod(0o755)
    assert m.logger.messages["error"] == [
        f"Cannot write {locked}/logo.png: Permission denied. {_OWNER_HINT} 1 asset(s) failed this way."
    ]
    assert os.listdir(dest / "Arrival (2016)") == ["logo.png"]
    assert db.media_asset_matches.get_one("media", 1, "logo")["match_status"] == "failed"


@_SKIP_AS_ROOT
def test_an_unreadable_source_warns_and_never_fails_the_run(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    logo = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    logo.chmod(0o000)
    try:
        m.run()
    finally:
        logo.chmod(0o644)
    assert m.logger.messages["error"] == []
    assert m.logger.messages["warning"] == [
        f"Asset file op failed for {logo} -> {dest}/Dune (2021)_logo.png: "
        f"[Errno 13] Permission denied: '{logo}'"
    ]
    assert list(dest.iterdir()) == []


@_SKIP_AS_ROOT
def test_a_destination_on_a_missing_volume_says_to_check_the_mount(db, monkeypatch, tmp_path):
    unmounted = tmp_path / "unmounted"
    unmounted.mkdir()
    dest = unmounted / "kometa"
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    unmounted.chmod(0o555)
    try:
        with pytest.raises(FileNotFoundError) as raised:
            m.run()
    finally:
        unmounted.chmod(0o755)
    assert str(raised.value) == (
        f"Could not create destination directory: {dest} ([Errno 13] Permission denied: "
        f"'{dest}'). Check the path is correct and its volume is mounted."
    )


@pytest.mark.parametrize("action", ["copy", "hardlink", "symlink"])
def test_an_asset_name_near_the_length_limit_is_still_placed(tmp_path, action):
    src = _make_src(tmp_path)
    dest = tmp_path / "kometa"
    dest.mkdir()
    target = dest / ("a" * 240 + "_logo.png")
    make_module(destination_dir=str(dest))._file_op(src, str(target), action)
    assert (os.listdir(dest), target.read_bytes()) == ([target.name], b"img")


def test_a_copy_never_writes_through_a_link_already_at_its_temp_name(tmp_path):
    src = _make_src(tmp_path)
    dest = tmp_path / "kometa"
    dest.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep")
    os.symlink(victim, dest / f".chub-tmp-{os.getpid()}-{threading.get_ident()}")
    m = make_module(destination_dir=str(dest))
    with pytest.raises(FileExistsError):
        m._file_op(src, str(dest / "Dune (2021)_logo.png"), "copy")
    assert (victim.read_bytes(), os.listdir(dest)) == (b"keep", [])


def test_a_copy_over_an_asset_another_user_owns_is_applied(db, monkeypatch, tmp_path):
    """Unraid's New Permissions leaves 0666 files CHUB can write but, as a non-owner, not chmod."""
    dest = tmp_path / "kometa"
    dest.mkdir()
    target = dest / "Dune (2021)_logo.png"
    target.write_bytes(b"old")
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    real_chmod = os.chmod

    def _chmod(path, *a, **k):
        if os.fspath(path) == str(target):
            raise PermissionError(errno.EPERM, "Operation not permitted", str(target))
        return real_chmod(path, *a, **k)

    monkeypatch.setattr(os, "chmod", _chmod)
    m.run()
    status = db.media_asset_matches.get_one("media", 1, "logo")["match_status"]

    assert (target.read_bytes(), status, os.listdir(dest)) == (
        b"png",
        "applied",
        ["Dune (2021)_logo.png"],
    )
    assert (m.logger.messages["warning"], m.logger.messages["error"]) == ([], [])


@_SKIP_AS_ROOT
def test_a_single_chosen_asset_keeps_its_own_warning(db, tmp_path):
    from tests.conftest import StubLogger

    dest = tmp_path / "kometa"
    dest.mkdir()
    logo = tmp_path / "Dune - Logo.png"
    logo.write_bytes(b"png")
    m = make_module(destination_dir=str(dest))
    m.logger = StubLogger()
    dune = {"id": 1, "title": "Dune", "year": 2021, "folder": "Dune (2021)"}
    dest.chmod(0o555)
    try:
        applied, detail = m.apply_chosen_asset(db, "media", dune, "logo", str(logo))
    finally:
        dest.chmod(0o755)
    assert (applied, detail) == (False, "file op failed: permission denied — see the server log")
    assert db.media_asset_matches.get_one("media", 1, "logo")["match_status"] == "failed"
    assert m.logger.messages["warning"] == [
        f"Asset file op failed for {logo} -> {dest}/Dune (2021)_logo.png: "
        f"[Errno 13] Permission denied: '{dest}/.chub-tmp-{os.getpid()}-{threading.get_ident()}'"
    ]


def _pick_arrival_when_placed(db, monkeypatch, tmp_path, dest, landed="Dune (2021)_logo.png", **over):
    """The user picks Arrival's logo in the UI once the run places ``landed``; returns the picked file."""
    picked = tmp_path / "picked.png"
    picked.write_bytes(b"picked")
    arrival = db.media.get_by_id(2)
    real_replace = os.replace
    done = []

    def _replace(src, dst, *a, **k):
        real_replace(src, dst, *a, **k)
        if os.path.basename(dst) == landed and not done:
            done.append(dst)
            make_module(destination_dir=str(dest), **over).apply_chosen_asset(
                db, "media", arrival, "logo", str(picked)
            )

    monkeypatch.setattr(os, "replace", _replace)
    return picked


def test_a_logo_picked_during_a_run_is_not_overwritten_by_it(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    _add_arrival(db, tmp_path)
    picked = _pick_arrival_when_placed(db, monkeypatch, tmp_path, dest)
    m.run()
    row = db.media_asset_matches.get_one("media", 2, "logo")
    assert (dest / "Arrival (2016)_logo.png").read_bytes() == b"picked"
    assert (row["matched_file"], row["user_confirmed"]) == (str(picked), 1)
    assert db.media_asset_matches.get_one("media", 1, "logo")["match_status"] == "applied"


def test_a_pick_for_an_item_with_no_art_survives_the_run(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    _add_arrival(db, tmp_path)
    (tmp_path / "src" / "Arrival (2016) {tmdb-329865} - Logo.png").unlink()
    picked = _pick_arrival_when_placed(db, monkeypatch, tmp_path, dest)
    m.run()
    row = db.media_asset_matches.get_one("media", 2, "logo")
    assert (row["matched_file"], row["match_status"], row["user_confirmed"]) == (
        str(picked),
        "applied",
        1,
    )


def test_a_pick_made_while_the_run_places_that_item_keeps_its_row(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    _add_arrival(db, tmp_path)
    picked = _pick_arrival_when_placed(
        db, monkeypatch, tmp_path, dest, landed="Arrival (2016)_logo.png"
    )
    m.run()
    row = db.media_asset_matches.get_one("media", 2, "logo")
    assert (dest / "Arrival (2016)_logo.png").read_bytes() == b"picked"
    assert (row["matched_file"], row["user_confirmed"]) == (str(picked), 1)


def test_a_repick_made_during_a_run_is_not_overwritten_by_the_old_pick(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    _add_arrival(db, tmp_path)
    old = tmp_path / "old.png"
    old.write_bytes(b"old")
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=2,
        image_type="logo",
        source="local",
        matched_file=str(old),
        match_status="failed",
    )
    db.media_asset_matches.set_user_confirmed("media", 2, "logo", True)
    picked = _pick_arrival_when_placed(db, monkeypatch, tmp_path, dest)
    m.run()
    row = db.media_asset_matches.get_one("media", 2, "logo")
    assert (dest / "Arrival (2016)_logo.png").read_bytes() == b"picked"
    assert (row["matched_file"], row["match_status"], row["user_confirmed"]) == (
        str(picked),
        "applied",
        1,
    )


def test_a_repick_of_an_item_whose_old_pick_and_art_are_gone_survives_the_run(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    _add_arrival(db, tmp_path)
    (tmp_path / "src" / "Arrival (2016) {tmdb-329865} - Logo.png").unlink()
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=2,
        image_type="logo",
        source="local",
        matched_file=str(tmp_path / "gone.png"),
        match_status="failed",
    )
    db.media_asset_matches.set_user_confirmed("media", 2, "logo", True)
    picked = _pick_arrival_when_placed(db, monkeypatch, tmp_path, dest)
    m.run()
    row = db.media_asset_matches.get_one("media", 2, "logo")
    assert (row["matched_file"], row["match_status"], row["user_confirmed"]) == (
        str(picked),
        "applied",
        1,
    )


def test_a_repick_is_locked_to_its_file_before_the_file_lands(db, monkeypatch, tmp_path):
    """A run reading the row while a re-picked file lands already sees the new pick."""
    dest = tmp_path / "kometa"
    dest.mkdir()
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=1,
        image_type="logo",
        source="local",
        matched_file=str(tmp_path / "old.png"),
        match_status="applied",
    )
    db.media_asset_matches.set_user_confirmed("media", 1, "logo", True)
    seen = []
    real_replace = os.replace

    def _replace(src, dst, *a, **k):
        seen.append(db.media_asset_matches.get_one("media", 1, "logo"))
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", _replace)
    dune = {"id": 1, "title": "Dune", "year": 2021, "folder": "Dune (2021)"}
    src = _make_src(tmp_path)
    make_module(destination_dir=str(dest)).apply_chosen_asset(db, "media", dune, "logo", src)
    assert [(row["user_confirmed"], row["matched_file"]) for row in seen] == [(1, src)]


def test_a_lock_on_a_vanished_file_still_takes_the_runs_match(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=1,
        image_type="logo",
        source="local",
        matched_file=str(tmp_path / "gone.png"),
        match_status="applied",
    )
    db.media_asset_matches.set_user_confirmed("media", 1, "logo", True)
    m.run()
    scanned = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (dest / "Dune (2021)_logo.png").read_bytes() == b"png"
    assert (row["matched_file"], row["match_status"]) == (str(scanned), "applied")


@_SKIP_AS_ROOT
def test_a_chosen_asset_moved_from_a_read_only_folder_is_applied_and_warns_at_once(db, tmp_path):
    from tests.conftest import StubLogger

    dest, picks = tmp_path / "kometa", tmp_path / "picks"
    dest.mkdir()
    picks.mkdir()
    logo = picks / "Dune - Logo.png"
    logo.write_bytes(b"png")
    m = make_module(destination_dir=str(dest), action_type="move")
    m.logger = StubLogger()
    dune = {"id": 1, "title": "Dune", "year": 2021, "folder": "Dune (2021)"}
    picks.chmod(0o555)
    try:
        applied, detail = m.apply_chosen_asset(db, "media", dune, "logo", str(logo))
    finally:
        picks.chmod(0o755)
    target = dest / "Dune (2021)_logo.png"
    assert (applied, detail, target.read_bytes(), logo.exists()) == (True, str(target), b"png", True)
    assert db.media_asset_matches.get_one("media", 1, "logo")["match_status"] == "applied"
    assert m.logger.messages["warning"] == [
        f"Moved a file but could not delete its source {logo}: Permission denied. "
        "Set File Action to copy, or let CHUB delete files in the source folder "
        "(a read/write mount, owned by PUID/PGID)."
    ]


def test_kometa_season_logo_naming(tmp_path):
    """A show season logo must use Kometa's Season##_logo form (PR #2681)."""
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa", asset_folders=True, destination_dir=str(dest)
    )
    media = _media(asset_type="show", season_number=2, folder="The Show (2020)")
    applied, path = m._apply_kometa(media, "logo", "local", src, None)
    assert applied
    assert path.endswith(os.path.join("The Show (2020)", "Season02_logo.png"))


def test_kometa_season_logo_flat_naming(tmp_path):
    dest = tmp_path / "assets"
    dest.mkdir()
    src = _make_src(tmp_path)
    m = make_module(
        apply_method="kometa", asset_folders=False, destination_dir=str(dest)
    )
    media = _media(asset_type="show", season_number=1, folder="The Show (2020)")
    applied, path = m._apply_kometa(media, "background", "local", src, None)
    assert applied
    assert os.path.basename(path) == "The Show (2020)_Season01_background.png"


# --------------------------------------------------------------------------
# apply capability matrix (Plex API + Kometa PR #2681)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image_type,method,ok",
    [
        ("logo", "plex", True),
        ("logo", "kometa", True),
        ("background", "plex", True),
        ("background", "kometa", True),
        ("squareart", "plex", True),
        ("squareart", "kometa", True),  # Kometa 2.4.5+ reads square art
        ("banner", "plex", False),  # no plexapi banner
        ("banner", "kometa", False),  # not read by Kometa
    ],
)
def test_apply_capability(image_type, method, ok):
    capable, reason = apply_capability(image_type, method)
    assert capable is ok
    if not ok:
        assert reason  # must explain why


# --------------------------------------------------------------------------
# no-bloat gating: assets are only scanned when the feature is enabled
# --------------------------------------------------------------------------


def _poster_module(run_asset_renamerr):
    m = object.__new__(PosterRenamerr)
    m.logger = _logger()
    m._cancel_event = None
    m.config = SimpleNamespace(run_asset_renamerr=run_asset_renamerr)
    m.full_config = SimpleNamespace(sync_gdrive=SimpleNamespace(gdrive_list=[]))
    return m


def test_scan_excludes_assets_when_feature_off(tmp_path):
    (tmp_path / "Movie (2020).png").write_bytes(b"p")
    (tmp_path / "Movie (2020) - Logo.png").write_bytes(b"l")
    m = _poster_module(run_asset_renamerr=False)
    recs = m._get_assets_files(str(tmp_path), include_assets=False)
    types = {r["image_type"] for r in recs}
    assert types == {"poster"}  # logo skipped entirely — no bloat for non-users


def test_scan_includes_assets_when_feature_on(tmp_path):
    (tmp_path / "Movie (2020).png").write_bytes(b"p")
    (tmp_path / "Movie (2020) - Logo.png").write_bytes(b"l")
    m = _poster_module(run_asset_renamerr=True)
    recs = m._get_assets_files(str(tmp_path), include_assets=True)
    types = {r["image_type"] for r in recs}
    assert types == {"poster", "logo"}


# --- #1 asset idempotency: skip unchanged re-applies -------------------------


def test_already_applied_skips_unchanged_fanart(db):
    m = make_module(sources=["fanart"], apply_method="plex")
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=1,
        image_type="logo",
        source="fanart",
        matched_url="http://x/l.png",
        applied_method="plex",
        match_status="applied",
    )
    # same url + applied + same method -> skip
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 1, "logo"),
            "plex",
            "fanart",
            None,
            "http://x/l.png",
            None,
        )
        is True
    )
    # different url -> don't skip
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 1, "logo"),
            "plex",
            "fanart",
            None,
            "http://x/OTHER.png",
            None,
        )
        is False
    )


def test_already_applied_local_mtime(db, tmp_path):
    f = str(tmp_path / "Movie - Logo.png")
    with open(f, "wb") as fh:
        fh.write(b"x")
    mtime = os.stat(f).st_mtime
    m = make_module(
        sources=["local"], apply_method="kometa", destination_dir=str(tmp_path)
    )
    dest = str(tmp_path / "out.png")
    with open(dest, "wb") as fh:
        fh.write(b"x")
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=2,
        image_type="logo",
        source="local",
        matched_file=f,
        source_mtime=mtime,
        applied_method="kometa",
        applied_path=dest,
        match_status="applied",
    )
    # unchanged mtime + applied_path exists -> skip
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 2, "logo"),
            "kometa",
            "local",
            f,
            None,
            mtime,
        )
        is True
    )
    # changed mtime -> don't skip
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 2, "logo"),
            "kometa",
            "local",
            f,
            None,
            mtime + 5,
        )
        is False
    )


def test_already_applied_direct_backfills_new_library(db):
    """A direct asset applied to only one library is re-applied when the config
    now targets a second library (per-library backfill), then skipped once both
    are covered."""
    m = make_module(
        sources=["fanart"],
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1",
                library_names=["Movies", "Movies 4K"],
                add_posters=True,
            )
        ],
    )
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=3,
        image_type="logo",
        source="fanart",
        matched_url="http://x/l.png",
        applied_method="plex",
        applied_libraries='["plex1/Movies"]',
        match_status="applied",
    )
    # "Movies 4K" not yet covered -> don't skip, so it gets backfilled.
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 3, "logo"),
            "plex",
            "fanart",
            None,
            "http://x/l.png",
            None,
            media={"title": "X"},
            is_collection=False,
        )
        is False
    )
    # Both libraries now covered -> skip.
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=3,
        image_type="logo",
        source="fanart",
        matched_url="http://x/l.png",
        applied_method="plex",
        applied_libraries='["plex1/Movies", "plex1/Movies 4K"]',
        match_status="applied",
    )
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 3, "logo"),
            "plex",
            "fanart",
            None,
            "http://x/l.png",
            None,
            media={"title": "X"},
            is_collection=False,
        )
        is True
    )


def test_already_applied_never_skips_in_dry_run(db):
    m = make_module(dry_run=True, sources=["fanart"], apply_method="plex")
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=3,
        image_type="logo",
        source="fanart",
        matched_url="http://x/l.png",
        applied_method="plex",
        match_status="applied",
    )
    assert (
        m._already_applied(
            db,
            db.media_asset_matches.get_one("media", 3, "logo"),
            "plex",
            "fanart",
            None,
            "http://x/l.png",
            None,
        )
        is False
    )


def test_dry_run_does_not_persist_match_state(db, monkeypatch):
    """A dry-run plex apply must NOT write media_asset_matches — otherwise the
    next REAL run's _already_applied check would skip an item that was never
    actually uploaded (the bug). The upload itself is also skipped."""
    m = make_module(
        dry_run=True,
        sources=["fanart"],
        apply_method="plex",
        asset_types=["logo"],
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Movies"], add_posters=True
            )
        ],
    )

    uploaded = []

    class FakeClient:
        def section_type(self, library_name):
            return "movie"

        def upload_logo(self, library_name, item_title, **kw):
            # Real PlexClient skips the actual call on dry_run; if this fires
            # during a dry run that's a separate bug. Record to assert it doesn't.
            if not kw.get("dry_run"):
                uploaded.append(library_name)
            return True  # mirrors _upload_artwork returning True even on dry-run

    m._plex_clients = {"plex1": FakeClient()}
    monkeypatch.setattr(m, "_gather_media", lambda _db: [_media(id=3)])
    monkeypatch.setattr(
        m,
        "_resolve_source",
        lambda *a, **k: ("fanart", None, "http://x/logo.png"),
    )

    out = m.match_and_apply_assets(db)

    # Reported as a (would-be) apply in the output...
    assert out["logo"] and out["logo"][0]["applied"] is True
    assert out["logo"][0]["dry_run"] is True
    # ...but NOTHING persisted, so a later real run still uploads.
    assert db.media_asset_matches.get_one("media", 3, "logo") is None
    # ...and no real upload happened.
    assert uploaded == []


def test_a_failed_fanart_upload_records_its_failure(db, monkeypatch):
    m = make_module(
        sources=["fanart"],
        apply_method="plex",
        asset_types=["logo"],
        plex_scope=[SimpleNamespace(instance="plex1", library_names=["Movies"], add_posters=True)],
    )

    class RefusingPlex:
        def section_type(self, library_name):
            return "movie"

        def upload_logo(self, library_name, item_title, **kw):
            return False

    m._plex_clients = {"plex1": RefusingPlex()}
    monkeypatch.setattr(m, "_gather_media", lambda _db: [_media(id=3)])
    # The fanart resolver's shape: no local file, only a URL.
    monkeypatch.setattr(m, "_resolve_source", lambda *a, **k: ("fanart", None, "http://x/logo.png"))
    out = m.match_and_apply_assets(db)
    row = db.media_asset_matches.get_one("media", 3, "logo")
    assert (out["logo"][0]["applied"], row["match_status"], row["matched_url"]) == (
        False,
        "failed",
        "http://x/logo.png",
    )


def test_apply_direct_uploads_to_all_matching_libraries():
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1",
                library_names=["Movies", "Movies 4K"],
                add_posters=True,
            )
        ],
    )

    class FakeClient:
        def upload_logo(self, library_name, item_title, **kw):
            return True

    m._plex_clients = {"plex1": FakeClient()}
    applied, detail, applied_libs = m._apply_direct(
        _empty_index_db(), _media(), "logo", "/x/l.png", None, False
    )
    assert applied is True
    # both libraries listed in the detail + returned for per-library tracking
    assert "Movies" in detail and "Movies 4K" in detail
    assert set(applied_libs) == {"plex1/Movies", "plex1/Movies 4K"}


def test_apply_direct_skips_type_mismatched_libraries():
    """A movie must not be searched/uploaded against a 'show' library — those
    are guaranteed misses (the old source of noisy 'not found' errors)."""
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1",
                library_names=["Films", "TV Programmes"],
                add_posters=True,
            )
        ],
    )

    uploaded_to = []

    class FakeClient:
        def section_type(self, library_name):
            return {"Films": "movie", "TV Programmes": "show"}.get(library_name)

        def upload_logo(self, library_name, item_title, **kw):
            uploaded_to.append(library_name)
            return True

    m._plex_clients = {"plex1": FakeClient()}
    applied, detail, applied_libs = m._apply_direct(
        _empty_index_db(), _media(), "logo", "/x/l.png", None, False
    )
    assert applied is True
    # only the movie-type library was touched; the show library was skipped
    assert uploaded_to == ["Films"]
    assert set(applied_libs) == {"plex1/Films"}
    # the type-filtered key set (used for idempotency) matches what was applied
    assert m._direct_target_lib_keys(_empty_index_db(), _media(), False) == {
        "plex1/Films"
    }


def test_apply_direct_uses_index_resolved_libraries():
    """When a PlexMediaIndex snapshot exists, the upload targets come from it
    (guid-matched, only libraries that actually hold the item) — not a live
    search, and intersected with the opted-in libraries."""
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Films", "Films 4K"], add_posters=True
            )
        ],
    )

    uploaded_to = []

    class FakeClient:
        def section_type(self, library_name):
            return "movie"  # would pass the live fallback too — but unused here

        def upload_logo(self, library_name, item_title, **kw):
            uploaded_to.append(library_name)
            return True

    m._plex_clients = {"plex1": FakeClient()}

    # Index snapshot: this movie (tmdb 1121330 — matches _media()) lives only in
    # "Films", even though "Films 4K" is also opted in.
    cache_rows = [
        {
            "plex_id": "100",
            "instance_name": "plex1",
            "asset_type": "movie",
            "library_name": "Films",
            "title": "8 A.M. Metro",
            "normalized_title": "8ammetro",
            "season_number": None,
            "guids": {"tmdb": "1121330"},
        }
    ]
    db = _empty_index_db(rows=cache_rows)

    applied, detail, applied_libs = m._apply_direct(
        db, _media(), "logo", "/x/l.png", None, False
    )
    assert applied is True
    # Resolved to the one library the index says holds it (guid match), not 4K.
    assert uploaded_to == ["Films"]
    assert set(applied_libs) == {"plex1/Films"}
    assert m._direct_target_lib_keys(db, _media(), False) == {"plex1/Films"}


def test_apply_direct_searches_live_when_the_snapshot_lacks_the_item():
    """An item added after the last Plex walk is not in the snapshot: search
    live instead of failing it as "not found" (the picker would also lock it)."""
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Films", "Films 4K"], add_posters=True
            )
        ],
    )
    searched = []

    class FakeClient:
        def section_type(self, library_name):
            return "movie"

        def upload_logo(self, library_name, item_title, **kw):
            searched.append((library_name, kw.get("plex_id")))
            return library_name == "Films"  # live search finds it there only

    m._plex_clients = {"plex1": FakeClient()}
    # The snapshot exists but holds another movie, not _media()'s tmdb 1121330.
    cache_rows = [
        {
            "plex_id": "7",
            "instance_name": "plex1",
            "asset_type": "movie",
            "library_name": "Films",
            "title": "Some Other Film",
            "normalized_title": "someotherfilm",
            "season_number": None,
            "guids": {"tmdb": "999"},
        }
    ]
    db = _empty_index_db(rows=cache_rows)

    applied, _detail, applied_libs = m._apply_direct(
        db, _media(), "logo", "/x/l.png", None, False
    )

    assert applied is True
    assert searched == [("Films", None), ("Films 4K", None)]
    assert applied_libs == ["plex1/Films"]


def test_apply_direct_uses_plex_title_and_rating_key():
    """Index hit: the upload targets the cached Plex ratingKey and the PLEX
    title/year — NOT the *arr title — so an item whose Plex title differs still
    resolves (e.g. Radarr 'Aliens vs Predator: Requiem' vs Plex
    'AVPR: Aliens vs Predator - Requiem')."""
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(instance="plex1", library_names=["Films"], add_posters=True)
        ],
    )
    calls = []

    class FakeClient:
        def upload_logo(self, library_name, item_title, **kw):
            calls.append((library_name, item_title, kw.get("year"), kw.get("plex_id")))
            return True

    m._plex_clients = {"plex1": FakeClient()}
    # Plex cache row: SAME tmdb guid as _media(), but a different Plex title/year.
    cache_rows = [
        {
            "plex_id": "218095",
            "instance_name": "plex1",
            "asset_type": "movie",
            "library_name": "Films",
            "title": "AVPR: Aliens vs Predator - Requiem",
            "normalized_title": "avpraliensvspredatorrequiem",
            "year": 2007,
            "season_number": None,
            "guids": {"tmdb": "1121330"},
        }
    ]
    db = _empty_index_db(rows=cache_rows)
    applied, detail, applied_libs = m._apply_direct(
        db, _media(), "logo", None, "http://x/l.png", is_collection=False
    )
    assert applied is True
    # Plex title + Plex year + cached ratingKey — not the *arr "8 A.M. Metro"/2023.
    assert calls == [("Films", "AVPR: Aliens vs Predator - Requiem", 2007, "218095")]
    assert set(applied_libs) == {"plex1/Films"}


# --- logging: print_only_renames + capability warn-once ---


def _capture_logger():
    from types import SimpleNamespace

    logs = {"info": [], "debug": [], "warning": [], "error": []}
    return (
        SimpleNamespace(
            info=lambda m, *a, **k: logs["info"].append(m),
            debug=lambda m, *a, **k: logs["debug"].append(m),
            warning=lambda m, *a, **k: logs["warning"].append(m),
            error=lambda m, *a, **k: logs["error"].append(m),
            get_adapter=lambda *a, **k: None,
        ),
        logs,
    )


def test_handle_output_print_only_renames_hides_unapplied():
    m = make_module(print_only_renames=True, asset_types=["logo"])
    logger, logs = _capture_logger()
    m.logger = logger
    output = {
        "logo": [
            {"title": "A", "year": 2020, "applied": True, "reason": "plex/Movies"},
            {"title": "B", "year": 2021, "applied": False, "reason": "not found"},
        ]
    }
    m.handle_output(output)
    joined = "\n".join(logs["info"])
    assert "A (2020)" in joined  # applied shown
    assert "B (2021)" not in joined  # unapplied hidden when print_only_renames
    assert "1/2 logo assets applied" in joined  # summary still shown


def test_handle_output_default_shows_all():
    m = make_module(print_only_renames=False, asset_types=["logo"])
    logger, logs = _capture_logger()
    m.logger = logger
    output = {
        "logo": [
            {"title": "A", "year": 2020, "applied": True, "reason": "ok"},
            {"title": "B", "year": 2021, "applied": False, "reason": "not found"},
        ]
    }
    m.handle_output(output)
    joined = "\n".join(logs["info"])
    assert "A (2020)" in joined and "B (2021)" in joined


# --------------------------------------------------------------------------
# release-readiness gate — Plex apply skips items with nothing in Plex
# --------------------------------------------------------------------------


def _gate_resolved_titles(db, apply_method):
    """Run match_and_apply_assets over one unreleased + one released item and
    return the titles that reached source resolution (i.e. were NOT gated)."""
    unreleased = {
        "id": 1,
        "asset_type": "movie",
        "title": "Avatar 4",
        "year": 2029,
        "status": "announced",
        "has_content": 0,
    }
    released = {
        "id": 2,
        "asset_type": "movie",
        "title": "Dune",
        "year": 2021,
        "status": "released",
        "has_content": 1,
    }
    m = make_module(
        sources=["local"],
        asset_types=["logo"],
        apply_method=apply_method,
        dry_run=True,
    )
    m._report_progress = lambda *a, **k: None
    m.is_cancelled = lambda: False
    m._gather_media = lambda _db: [unreleased, released]
    resolved = []
    m._resolve_source = lambda media, *a, **k: resolved.append(media["title"])
    m.match_and_apply_assets(db)
    return resolved


def test_plex_apply_gates_unreleased_item(db):
    # Plex path: the unreleased/undownloaded item is skipped before resolution;
    # the released item still resolves.
    resolved = _gate_resolved_titles(db, "plex")
    assert "Avatar 4" not in resolved
    assert "Dune" in resolved


def test_kometa_apply_does_not_gate(db):
    # Kometa path writes to asset folders regardless of Plex — the gate is
    # exempt, so both items resolve.
    resolved = _gate_resolved_titles(db, "kometa")
    assert "Avatar 4" in resolved
    assert "Dune" in resolved


# --------------------------------------------------------------------------
# match_and_apply_assets — provenance: record a "missing" row when an item has
# no source artwork, so the Unmatched view derives coverage from the table
# (a reset empties it → 0; the next run repopulates it).
# --------------------------------------------------------------------------


def _run_no_source(db, media_id=7, **overrides):
    """Drive match_and_apply_assets over one released item whose source never
    resolves (no artwork anywhere). Returns the item id."""
    media = {
        "id": media_id,
        "asset_type": "movie",
        "title": "No Art",
        "year": 2021,
        "status": "released",
        "has_content": 1,
    }
    cfg = dict(sources=["local"], asset_types=["logo"], apply_method="kometa")
    cfg.update(overrides)
    m = make_module(**cfg)
    m._report_progress = lambda *a, **k: None
    m.is_cancelled = lambda: False
    m._gather_media = lambda _db: [media]
    m._resolve_source = lambda *a, **k: None  # no source artwork anywhere
    m.match_and_apply_assets(db)
    return media_id


def test_missing_row_recorded_when_no_source(db):
    mid = _run_no_source(db)
    row = db.media_asset_matches.get_one("media", mid, "logo")
    assert row is not None
    assert row["match_status"] == "missing"
    assert row["detail"] == "no source artwork found"


def test_missing_row_not_written_on_dry_run(db):
    mid = _run_no_source(db, dry_run=True)
    assert db.media_asset_matches.get_one("media", mid, "logo") is None


def test_missing_does_not_downgrade_applied(db):
    mid = 7
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=mid,
        image_type="logo",
        source="tmdb",
        match_status="applied",
    )
    _run_no_source(db, media_id=mid)
    row = db.media_asset_matches.get_one("media", mid, "logo")
    assert row["match_status"] == "applied"  # not flipped to "missing"


def test_kometa_never_applies_fanart_no_download(tmp_path):
    """Kometa applies LOCAL g-drive files only. fanart art is Plex-only (it
    would require downloading a copy, against fanart.tv's API use), so the
    Kometa apply refuses a fanart source outright and writes nothing."""
    m = make_module(
        sources=["local", "fanart"],
        apply_method="kometa",
        destination_dir=str(tmp_path),
    )
    applied, reason = m._apply_kometa(
        _media(), "logo", "fanart", None, "https://assets.fanart.tv/x/logo.png"
    )
    assert applied is False
    assert "plex" in reason.lower()
    # Nothing was downloaded or written to disk.
    assert list(tmp_path.iterdir()) == []


# --- _file_op link safety ---


def test_file_op_hardlink_failure_preserves_destination(tmp_path):
    """A failed link must never destroy the existing destination file
    (the old implementation removed dest before linking)."""
    m = make_module()
    dest = tmp_path / "logo.png"
    dest.write_bytes(b"existing")
    missing_src = str(tmp_path / "vanished.png")
    import pytest as _pytest

    with _pytest.raises(OSError):
        m._file_op(missing_src, str(dest), "hardlink")
    assert dest.read_bytes() == b"existing"
    # No temp debris left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["logo.png"]


def test_file_op_hardlink_replaces_destination(tmp_path):
    m = make_module()
    src = tmp_path / "src.png"
    src.write_bytes(b"new")
    dest = tmp_path / "logo.png"
    dest.write_bytes(b"old")
    m._file_op(str(src), str(dest), "hardlink")
    assert dest.read_bytes() == b"new"
    import os as _os

    assert _os.stat(dest).st_ino == _os.stat(src).st_ino


def test_file_op_symlink_replaces_destination(tmp_path):
    m = make_module()
    src = tmp_path / "src.png"
    src.write_bytes(b"new")
    dest = tmp_path / "logo.png"
    dest.write_bytes(b"old")
    m._file_op(str(src), str(dest), "symlink")
    assert dest.is_symlink() and dest.read_bytes() == b"new"


# --- season+logo coverage (clear logos are show-level only) ---


def _insert_media(db, title, asset_type, season_number=None):
    return db.media.execute_query(
        "INSERT INTO media_cache (identity_key, title, asset_type, season_number) "
        "VALUES (?, ?, ?, ?)",
        (f"{asset_type}:{title}:{season_number}", title, asset_type, season_number),
        last_row_id=True,
    )


def test_purge_season_logos_removes_only_season_logo_rows(db):
    """purge_season_logos deletes logo rows targeting season rows — and nothing
    else: show-level logos, movie logos and season background/squareart rows
    all survive (seasons keep their other artwork expectations)."""
    show_id = _insert_media(db, "Show X", "show")
    season_id = _insert_media(db, "Show X", "show", season_number=1)
    movie_id = _insert_media(db, "Movie Y", "movie")
    m = db.media_asset_matches
    m.upsert(
        target_kind="media",
        target_id=show_id,
        image_type="logo",
        match_status="missing",
    )
    m.upsert(
        target_kind="media",
        target_id=season_id,
        image_type="logo",
        match_status="missing",
    )
    m.upsert(
        target_kind="media",
        target_id=season_id,
        image_type="background",
        match_status="missing",
    )
    m.upsert(
        target_kind="media",
        target_id=movie_id,
        image_type="logo",
        match_status="applied",
    )

    assert m.purge_season_logos() == 1
    kept = {(r["target_id"], r["image_type"]) for r in m.get_all()}
    assert kept == {
        (show_id, "logo"),
        (season_id, "background"),
        (movie_id, "logo"),
    }
    # Idempotent: nothing left to purge on a second pass.
    assert m.purge_season_logos() == 0


# --------------------------------------------------------------------------
# Kometa square art (2.4.5+) and album asset naming
# --------------------------------------------------------------------------


def _kometa_dest(tmp_path, media, image_type, asset_folders):
    m = make_module(
        apply_method="kometa",
        destination_dir=str(tmp_path),
        asset_folders=asset_folders,
        dry_run=True,
    )
    ok, dest = m._apply_kometa(media, image_type, "local", "/src/art.png", None)
    assert ok, dest
    return os.path.relpath(dest, str(tmp_path))


def test_squareart_writes_kometas_square_name(tmp_path):
    # Kometa's first-choice stem is a bare "square" in both layouts.
    media = _media(folder="The Matrix (1999) {tmdb-603}")
    assert (
        _kometa_dest(tmp_path, media, "squareart", True)
        == "The Matrix (1999) {tmdb-603}/square.png"
    )
    assert (
        _kometa_dest(tmp_path, media, "squareart", False)
        == "The Matrix (1999) {tmdb-603}_square.png"
    )


def test_album_asset_does_not_collide_with_its_artist(tmp_path):
    # Every album used to write <Artist folder>/background.png, overwriting the
    # artist's own art and each sibling album's.
    artist = _media(asset_type="artist", title="Pink Floyd", folder="Pink Floyd")
    album = _media(asset_type="album", title="The Wall", folder="Pink Floyd")
    other = _media(asset_type="album", title="Animals", folder="Pink Floyd")
    paths = {
        _kometa_dest(tmp_path, artist, "background", True),
        _kometa_dest(tmp_path, album, "background", True),
        _kometa_dest(tmp_path, other, "background", True),
    }
    assert len(paths) == 3, f"collision: {paths}"
    assert "Pink Floyd/The Wall_background.png" in paths
    assert "Pink Floyd/background.png" in paths


def test_album_asset_flat_layout(tmp_path):
    album = _media(asset_type="album", title="The Wall", folder="Pink Floyd")
    assert (
        _kometa_dest(tmp_path, album, "background", False)
        == "Pink Floyd_The Wall_background.png"
    )


# --------------------------------------------------------------------------
# Kometa asset_folders layout: bare stems key on the parent folder
# --------------------------------------------------------------------------

_FOLDER = "/x/The Matrix (1999) {tmdb-603}"


@pytest.mark.parametrize(
    "fname,image_type",
    [
        ("poster.jpg", "poster"),
        ("cover.jpg", "poster"),
        ("default.png", "poster"),
        ("folder.tbn", "poster"),
        ("movie.jpg", "poster"),
        ("background.png", "background"),
        ("art.jpg", "background"),
        ("backdrop.png", "background"),
        ("fanart.png", "background"),
        ("logo.png", "logo"),
        ("clearlogo.png", "logo"),
        ("square.png", "squareart"),
        ("square_art.png", "squareart"),
        ("squareArt.png", "squareart"),
        ("backgroundSquare.png", "squareart"),
    ],
)
def test_foldered_stem_types_and_identity(fname, image_type):
    """A bare Kometa stem carries only the TYPE — identity is the parent folder.

    Previously every one of these keyed on the stem itself ("logo", "square"),
    so a foldered tree scanned as posters titled after their asset type.
    """
    rec = build_asset_record(fname, _FOLDER)
    assert rec["image_type"] == image_type
    assert rec["title"] == "The Matrix"
    assert rec["normalized_title"] == "thematrix"
    assert rec["tmdb_id"] == 603
    assert rec["year"] == 1999


@pytest.mark.parametrize(
    "fname,image_type,season",
    [("Season01.jpg", "poster", 1), ("Season01_background.png", "background", 1),
     ("Season00.jpg", "poster", 0), ("Season100.jpg", "poster", 100)],
)
def test_foldered_season_stems(fname, image_type, season):
    # season_number_regex needs a delimiter, so a bare "Season01" matched nothing.
    rec = build_asset_record(fname, _FOLDER)
    assert rec["image_type"] == image_type
    assert rec["season_number"] == season
    assert rec["normalized_title"] == "thematrix"


@pytest.mark.parametrize(
    "fname,image_type,title",
    [
        ("Movie (1999) {tmdb-1} - Logo.png", "logo", "Movie"),
        ("Movie (1999) {tmdb-1} - SquareArt.png", "squareart", "Movie"),
        ("Movie (1999) {tmdb-1}.png", "poster", "Movie"),
        # A real title that merely CONTAINS a stem word must not be eaten.
        ("Open Season 2 (2008) - Logo.png", "logo", "Open Season 2"),
        ("The Square (2017) {tmdb-2}.jpg", "poster", "The Square"),
        ("Background Noise (2010).png", "poster", "Background Noise"),
    ],
)
def test_flat_convention_is_unchanged(fname, image_type, title):
    rec = build_asset_record(fname, "/x/src")
    assert rec["image_type"] == image_type
    assert rec["title"] == title


@pytest.mark.parametrize(
    "fname", ["Cover.jpg", "Art.jpg", "Movie.jpg", "Folder.jpg", "Square.jpg", "Logo.png"]
)
def test_flat_file_named_after_a_stem_keeps_its_own_title(fname):
    """parse_asset_type can't see the layout, so a flat file literally named
    "Cover.jpg" looked like a foldered stem and took the DRIVE folder's name —
    collapsing every such file onto one match key."""
    rec = build_asset_record(fname, "/kometa/posters/MM2K/Chodeus")
    stem = os.path.splitext(fname)[0]
    assert rec["image_type"] == "poster"
    assert rec["title"] == stem
    assert rec["normalized_title"] == stem.lower()


@pytest.mark.parametrize("folder", ["Some Show (2020)", "Some Show {tmdb-42}"])
def test_foldered_stem_needs_only_a_year_or_an_id_on_the_parent(folder):
    rec = build_asset_record("logo.png", f"/x/{folder}")
    assert rec["image_type"] == "logo"
    assert rec["normalized_title"] == "someshow"


def _remaining_setup():
    """Films + Films 4K opted in; the snapshot lacks _media(), so both are live-searched."""
    m = make_module(
        apply_method="plex",
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Films", "Films 4K"], add_posters=True
            )
        ],
    )
    uploaded = []

    class FakeClient:
        def section_type(self, library_name):
            return "movie"

        def upload_logo(self, library_name, item_title, **kw):
            uploaded.append(library_name)
            return library_name == "Films"  # the 4K library does not hold it

    m._plex_clients = {"plex1": FakeClient()}
    other = [
        {
            "plex_id": "7",
            "instance_name": "plex1",
            "asset_type": "movie",
            "library_name": "Films",
            "title": "Some Other Film",
            "normalized_title": "someotherfilm",
            "season_number": None,
            "guids": {"tmdb": "999"},
        }
    ]
    return m, _empty_index_db(rows=other), uploaded


def _prev(url="http://x/l.png", libraries='["plex1/Films"]'):
    return {
        "match_status": "applied",
        "applied_method": "plex",
        "source": "fanart",
        "matched_url": url,
        "applied_libraries": libraries,
    }


def test_scheduled_apply_skips_libraries_the_same_source_already_reached():
    m, db, uploaded = _remaining_setup()

    applied, detail, libs = m._apply_direct_remaining(
        db, _media(), "logo", None, "http://x/l.png", False, _prev(), "fanart", None
    )

    assert uploaded == ["Films 4K"]  # Films already holds this exact asset
    assert (applied, libs) == (True, ["plex1/Films"])
    assert detail == "plex1/Films"


def test_scheduled_apply_uploads_everywhere_when_the_source_changed():
    m, db, uploaded = _remaining_setup()

    applied, _detail, libs = m._apply_direct_remaining(
        db,
        _media(),
        "logo",
        None,
        "http://x/new.png",
        False,
        _prev(url="http://x/old.png"),
        "fanart",
        None,
    )

    assert uploaded == ["Films", "Films 4K"]
    assert (applied, libs) == (True, ["plex1/Films"])


def test_scheduled_apply_drops_a_recorded_library_that_is_no_longer_targeted():
    m, db, uploaded = _remaining_setup()
    prev = _prev(libraries='["plex1/Films", "plex1/Old Library"]')

    applied, _detail, libs = m._apply_direct_remaining(
        db, _media(), "logo", None, "http://x/l.png", False, prev, "fanart", None
    )

    assert uploaded == ["Films 4K"]
    assert (applied, libs) == (True, ["plex1/Films"])


def test_scheduled_apply_fails_when_only_an_untargeted_library_had_it():
    m, db, uploaded = _remaining_setup()
    prev = _prev(libraries='["plex1/Old Library"]')

    class NothingHolds:
        def section_type(self, library_name):
            return "movie"

        def upload_logo(self, library_name, item_title, **kw):
            uploaded.append(library_name)
            return False

    m._plex_clients = {"plex1": NothingHolds()}

    applied, _detail, libs = m._apply_direct_remaining(
        db, _media(), "logo", None, "http://x/l.png", False, prev, "fanart", None
    )

    assert uploaded == ["Films", "Films 4K"]
    assert (applied, libs) == (False, [])


def test_recorded_libraries_needs_the_same_unchanged_source():
    m = make_module(apply_method="plex")
    local = {
        "match_status": "applied",
        "applied_method": "plex",
        "source": "local",
        "matched_file": "/a/logo.png",
        "source_mtime": 100.0,
        "applied_libraries": '["plex1/Films"]',
    }

    same = m._recorded_libraries(local, "plex", "local", "/a/logo.png", None, 100.0)
    touched = m._recorded_libraries(local, "plex", "local", "/a/logo.png", None, 200.0)
    failed = m._recorded_libraries(
        {**local, "match_status": "failed"}, "plex", "local", "/a/logo.png", None, 100.0
    )

    assert (same, touched, failed) == ({"plex1/Films"}, None, None)


def test_a_second_run_does_not_reupload_where_the_asset_already_landed(db, monkeypatch):
    """No snapshot: both libraries are live-searched. The 4K one never holds the
    item, so each run retries it, but Films already has this exact logo."""
    m = make_module(
        sources=["fanart"],
        apply_method="plex",
        asset_types=["logo"],
        plex_scope=[
            SimpleNamespace(
                instance="plex1", library_names=["Films", "Films 4K"], add_posters=True
            )
        ],
    )
    uploaded = []

    class FakeClient:
        def section_type(self, library_name):
            return "movie"

        def upload_logo(self, library_name, item_title, **kw):
            uploaded.append(library_name)
            return library_name == "Films"

    m._plex_clients = {"plex1": FakeClient()}
    monkeypatch.setattr(m, "_gather_media", lambda _db: [_media(id=3)])
    monkeypatch.setattr(
        m, "_resolve_source", lambda *a, **k: ("fanart", None, "http://x/logo.png")
    )

    m.match_and_apply_assets(db)
    m.match_and_apply_assets(db)

    assert uploaded == ["Films", "Films 4K", "Films 4K"]
    row = db.media_asset_matches.get_one("media", 3, "logo")
    assert (row["match_status"], row["applied_libraries"]) == ("applied", '["plex1/Films"]')


def test_re_picking_a_hardlinked_logo_leaves_no_temp_and_the_next_asset_lands(db, tmp_path):
    dest, picks = tmp_path / "kometa", tmp_path / "picks"
    dest.mkdir()
    picks.mkdir()
    logo, bg = picks / "Dune - Logo.png", picks / "Dune - Background.jpg"
    logo.write_bytes(b"logo")
    bg.write_bytes(b"bg")
    m = make_module(destination_dir=str(dest), action_type="hardlink")
    dune = {"id": 1, "title": "Dune", "year": 2021, "folder": "Dune (2021)"}
    first = m.apply_chosen_asset(db, "media", dune, "logo", str(logo))
    repick = m.apply_chosen_asset(db, "media", dune, "logo", str(logo))
    applied, detail = m.apply_chosen_asset(db, "media", dune, "background", str(bg))
    assert (first[0], repick[0], applied) == (True, True, True), detail
    assert sorted(os.listdir(dest)) == ["Dune (2021)_background.jpg", "Dune (2021)_logo.png"]


def _moved_pick(db, monkeypatch, tmp_path):
    """A logo picked with File Action "move" before a run that also finds Dune's own logo; returns (module, placed)."""
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    pick = tmp_path / "picks" / "mine.png"
    pick.parent.mkdir()
    pick.write_bytes(b"my pick")
    applied, detail = m.apply_chosen_asset(db, "media", db.media.get_by_id(1), "logo", str(pick))
    placed = dest / "Dune (2021)_logo.png"
    assert (applied, placed.read_bytes(), pick.exists()) == (True, b"my pick", False), detail
    return m, placed


def test_a_run_keeps_a_logo_picked_with_move(db, monkeypatch, tmp_path):
    m, placed = _moved_pick(db, monkeypatch, tmp_path)
    m.run()
    assert placed.read_bytes() == b"my pick"
    assert db.media_asset_matches.get_one("media", 1, "logo")["user_confirmed"]


def test_a_run_places_the_found_logo_once_a_moved_pick_is_deleted_from_kometa(db, monkeypatch, tmp_path):
    m, placed = _moved_pick(db, monkeypatch, tmp_path)
    placed.unlink()
    m.run()
    assert placed.read_bytes() == b"png"


def test_a_logo_picked_with_move_follows_a_new_destination(db, monkeypatch, tmp_path):
    m, placed = _moved_pick(db, monkeypatch, tmp_path)
    new_dest = tmp_path / "kometa2"
    new_dest.mkdir()
    m.config.destination_dir = str(new_dest)
    m.run()
    landed = new_dest / "Dune (2021)_logo.png"
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (landed.read_bytes(), placed.exists(), row["user_confirmed"]) == (b"my pick", False, 1)
    m.run()
    with open(landed, "rb") as f:
        kept = f.read()
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (kept, row["applied_path"]) == (b"my pick", str(landed))


@pytest.mark.parametrize("action_type", ["copy", "hardlink"])
def test_an_unchanged_logo_follows_a_new_destination(db, monkeypatch, tmp_path, action_type):
    dest, new_dest = tmp_path / "kometa", tmp_path / "kometa2"
    dest.mkdir()
    new_dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type=action_type)
    m.run()
    m.config.destination_dir = str(new_dest)
    m.run()
    landed = new_dest / "Dune (2021)_logo.png"
    with open(landed, "rb") as f:
        placed = f.read()
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (placed, row["applied_path"]) == (b"png", str(landed))


def test_a_logo_found_and_moved_follows_a_new_destination(db, monkeypatch, tmp_path):
    dest, new_dest = tmp_path / "kometa", tmp_path / "kometa2"
    dest.mkdir()
    new_dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    placed = dest / "Dune (2021)_logo.png"
    src_left = list((tmp_path / "src").iterdir())
    assert (placed.read_bytes(), src_left) == (b"png", [])
    m.config.destination_dir = str(new_dest)
    m.run()
    landed = new_dest / "Dune (2021)_logo.png"
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (landed.read_bytes(), placed.exists(), row["match_status"]) == (b"png", False, "applied")
    m.run()
    with open(landed, "rb") as f:
        kept = f.read()
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (kept, row["applied_path"], row["match_status"]) == (b"png", str(landed), "applied")


def test_a_moved_logo_follows_a_new_destination_while_its_source_root_is_missing(db, monkeypatch, tmp_path):
    dest, new_dest = tmp_path / "kometa", tmp_path / "kometa2"
    dest.mkdir()
    new_dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    src = tmp_path / "src"
    src.rmdir()  # the source drive is unmounted; its cached scan rows stay
    m.config.destination_dir = str(new_dest)
    m.run()
    landed = new_dest / "Dune (2021)_logo.png"
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (landed.read_bytes(), (dest / "Dune (2021)_logo.png").exists()) == (b"png", False)
    assert (row["match_status"], row["applied_path"]) == ("applied", str(landed))
    assert (m.logger.messages["warning"], m.logger.messages["error"]) == ([f"Source dir not found: '{src}'"], [])


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_moved_logo_that_cannot_reach_a_new_destination_is_retried(db, monkeypatch, tmp_path):
    from backend.modules.asset_renamerr import NoAssetWritten

    dest, new_dest = tmp_path / "kometa", tmp_path / "kometa2"
    dest.mkdir()
    blocked = new_dest / "Dune (2021)"
    blocked.mkdir(parents=True)
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move", asset_folders=True)
    m.run()
    placed = dest / "Dune (2021)" / "logo.png"
    m.config.destination_dir = str(new_dest)
    blocked.chmod(0o555)
    try:
        with pytest.raises(NoAssetWritten):
            m.run()
    finally:
        blocked.chmod(0o755)
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (placed.read_bytes(), row["applied_path"]) == (b"png", str(placed))
    m.run()
    assert ((blocked / "logo.png").read_bytes(), placed.exists()) == (b"png", False)


def test_a_moved_pick_stays_a_file_after_the_action_becomes_symlink(db, monkeypatch, tmp_path):
    m, placed = _moved_pick(db, monkeypatch, tmp_path)
    m.config.action_type = "symlink"
    m.run()
    with open(placed, "rb") as f:
        kept = f.read()
    assert (placed.is_symlink(), kept) == (False, b"my pick")


def _logo_run_then_rename(db, monkeypatch, tmp_path, **over):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, **over)
    m.run()
    db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("Dune (2021) [renamed]",))
    return m, dest


def _tree(dest):
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*"))


@pytest.mark.parametrize("asset_folders", [False, True])
@pytest.mark.parametrize("action_type", ["copy", "hardlink", "symlink"])
def test_a_logo_whose_folder_is_renamed_leaves_no_old_file(db, monkeypatch, tmp_path, action_type, asset_folders):
    m, dest = _logo_run_then_rename(db, monkeypatch, tmp_path, action_type=action_type, asset_folders=asset_folders)
    m.run()
    landed = ["Dune (2021) [renamed]", "Dune (2021) [renamed]/logo.png"] if asset_folders else ["Dune (2021) [renamed]_logo.png"]
    src = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    assert (_tree(dest), src.read_bytes(), m.logger.messages["warning"]) == (landed, b"png", [])


def test_a_logo_leaves_no_empty_folder_once_asset_folders_is_off(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, asset_folders=True)
    m.run()
    m.config.asset_folders = False
    m.run()
    assert _tree(dest) == ["Dune (2021)_logo.png"]


def test_a_hardlinked_logo_relinked_to_its_source_leaves_no_old_file(db, monkeypatch, tmp_path):
    m, dest = _logo_run_then_rename(db, monkeypatch, tmp_path, action_type="hardlink")
    m.config.action_type = "symlink"
    m.run()
    landed = dest / "Dune (2021) [renamed]_logo.png"
    assert (_tree(dest), landed.is_symlink(), landed.read_bytes()) == ([landed.name], True, b"png")


def test_a_case_only_folder_rename_keeps_the_logo_on_a_case_insensitive_mount(db, monkeypatch, tmp_path):
    (tmp_path / "probe").touch()
    if not (tmp_path / "PROBE").exists():
        pytest.skip("needs a case-insensitive filesystem")
    m, dest = _logo_run_then_rename(db, monkeypatch, tmp_path)
    db.media.execute_query("UPDATE media_cache SET folder=? WHERE id=1", ("DUNE (2021)",))
    m.run()
    assert [p.read_bytes() for p in dest.iterdir()] == [b"png"]


@pytest.mark.parametrize("action_type", ["copy", "move"])
@pytest.mark.parametrize("live", [True, False], ids=["live", "deleted"])
def test_a_logo_another_item_records_stays_after_a_rename(db, monkeypatch, tmp_path, live, action_type):
    m, dest = _logo_run_then_rename(db, monkeypatch, tmp_path, action_type=action_type)
    other = db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, folder, asset_type) VALUES (?,?,?,?)",
        ("radarr-4k|Dune (2021)|None", "radarr-4k", "Dune (2021)", "movie"),
        last_row_id=True,
    )
    if not live:
        db.media.execute_query("DELETE FROM media_cache WHERE id=?", (other,))
    old = db.media_asset_matches.get_one("media", 1, "logo")["applied_path"]
    db.media_asset_matches.upsert(
        target_kind="media", target_id=other, image_type="logo", source="local", matched_file=old,
        applied_method="kometa", applied_path=old, match_status="applied",
    )
    m.run()
    assert (os.path.exists(old), (dest / "Dune (2021) [renamed]_logo.png").exists()) == (live, True)


def test_a_dry_run_keeps_the_logo_placed_under_the_old_folder_name(db, monkeypatch, tmp_path):
    m, dest = _logo_run_then_rename(db, monkeypatch, tmp_path)
    m.config.dry_run = True
    m.run()
    assert _tree(dest) == ["Dune (2021)_logo.png"]


def test_a_moved_logo_carried_as_a_symlink_keeps_the_file_it_links_to(db, monkeypatch, tmp_path):
    m, dest = _logo_run_then_rename(db, monkeypatch, tmp_path, action_type="move")
    m.config.action_type = "symlink"
    m.run()
    landed = dest / "Dune (2021) [renamed]_logo.png"
    assert (landed.is_symlink(), landed.read_bytes()) == (True, b"png")


def test_a_logo_picked_with_another_extension_replaces_the_old_file(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    m.run()
    pick = tmp_path / "picks" / "mine.jpg"
    pick.parent.mkdir()
    pick.write_bytes(b"my pick")
    applied, detail = m.apply_chosen_asset(db, "media", db.media.get_by_id(1), "logo", str(pick))
    assert (applied, _tree(dest), (dest / "Dune (2021)_logo.jpg").read_bytes()) == (
        True, ["Dune (2021)_logo.jpg"], b"my pick"
    ), detail


def _symlinked_logo(db, monkeypatch, tmp_path):
    """A real run symlinks Dune's scanned logo into Kometa; returns (module, placed link, its source)."""
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="symlink")
    m.run()
    placed = dest / "Dune (2021)_logo.png"
    src = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    assert (placed.is_symlink(), os.path.realpath(placed)) == (True, os.path.realpath(src))
    return m, placed, src


def _pick_logo(m, db, tmp_path):
    pick = tmp_path / "picks" / "mine.png"
    pick.parent.mkdir()
    pick.write_bytes(b"my pick")
    return pick, m.apply_chosen_asset(db, "media", db.media.get_by_id(1), "logo", str(pick))


def test_a_symlinked_logo_takes_a_new_pick_and_keeps_its_source(db, monkeypatch, tmp_path):
    m, placed, src = _symlinked_logo(db, monkeypatch, tmp_path)
    pick, (applied, detail) = _pick_logo(m, db, tmp_path)
    with open(placed, "rb") as f:
        shown = f.read()
    assert (applied, detail) == (True, os.path.join(os.path.realpath(placed.parent), placed.name))
    assert (os.path.realpath(placed), shown, src.read_bytes()) == (os.path.realpath(pick), b"my pick", b"png")
    m.logger.messages["debug"].clear()
    m.run()
    relinked = [line for line in m.logger.messages["debug"] if line.startswith("[SYMLINK]")]
    assert (os.path.realpath(placed), relinked, m.logger.messages["warning"]) == (os.path.realpath(pick), [], [])


def test_a_symlinked_logo_whose_source_changed_is_linked_again(db, monkeypatch, tmp_path):
    m, placed, src = _symlinked_logo(db, monkeypatch, tmp_path)
    later = os.stat(src).st_mtime + 60
    os.utime(src, (later, later))
    m.run()
    row = db.media_asset_matches.get_one("media", 1, "logo")
    assert (row["match_status"], row["source_mtime"], placed.is_symlink()) == ("applied", later, True)
    assert (m.logger.messages["warning"], m.logger.messages["error"]) == ([], [])


def test_a_symlinked_logo_becomes_a_file_once_the_action_is_move(db, monkeypatch, tmp_path):
    m, placed, src = _symlinked_logo(db, monkeypatch, tmp_path)
    m.config.action_type = "move"
    pick, (applied, _detail) = _pick_logo(m, db, tmp_path)
    assert (applied, placed.is_symlink(), placed.read_bytes()) == (True, False, b"my pick")
    assert (pick.exists(), src.read_bytes()) == (False, b"png")


@pytest.mark.parametrize("action", ["copy", "hardlink", "move"])
def test_a_symlinked_logo_becomes_a_file_once_the_action_is_not_symlink(db, monkeypatch, tmp_path, action):
    m, placed, src = _symlinked_logo(db, monkeypatch, tmp_path)
    m.config.action_type = action
    m.run()
    assert (placed.is_symlink(), placed.read_bytes(), src.exists()) == (False, b"png", action != "move")
    assert (src.exists() and os.path.samefile(placed, src)) == (action == "hardlink")
    before = os.lstat(placed)
    m.run()
    after = os.lstat(placed)
    assert (after.st_ino, after.st_ctime_ns) == (before.st_ino, before.st_ctime_ns)
    assert m.logger.messages["warning"] == []


@pytest.mark.parametrize("action", ["copy", "hardlink", "move"])
def test_a_symlinked_logo_whose_source_is_no_longer_listed_becomes_a_file(db, monkeypatch, tmp_path, action):
    m, placed, src = _symlinked_logo(db, monkeypatch, tmp_path)
    m.config.source_dirs = []
    db.poster.delete_asset_rows_by_path_prefix(str(src.parent))
    m.config.action_type = action
    m.run()
    assert (placed.is_symlink(), placed.read_bytes(), src.read_bytes()) == (False, b"png", b"png")
    assert os.path.samefile(placed, src) == (action == "hardlink")
    before = os.lstat(placed)
    m.run()
    after = os.lstat(placed)
    assert (after.st_ino, after.st_ctime_ns, m.logger.messages["warning"]) == (before.st_ino, before.st_ctime_ns, [])


def test_a_logo_picked_with_move_during_a_run_stays_through_the_next_run(db, monkeypatch, tmp_path):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _add_arrival(db, tmp_path)
    picked = _pick_arrival_when_placed(db, monkeypatch, tmp_path, dest, action_type="move")
    placed = dest / "Arrival (2016)_logo.png"
    m.run()
    assert (placed.read_bytes(), picked.exists()) == (b"picked", False)
    m.run()
    assert placed.read_bytes() == b"picked"


def test_a_plex_run_does_not_count_a_kometa_copy_as_the_pick(tmp_path):
    placed = tmp_path / "Dune (2021)_logo.png"
    placed.write_bytes(b"my pick")
    locked = {"user_confirmed": 1, "applied_path": str(placed)}
    assert make_module(apply_method="plex")._placed_file(locked) is None
    assert make_module(apply_method="kometa")._placed_file(locked) == str(placed)


def _dune_in(db, instance, folder):
    """Dune as a second *arr instance lists it, in its own folder."""
    db.media.upsert(
        {
            "title": "Dune",
            "normalized_title": "dune",
            "alternate_titles": "[]",
            "year": 2021,
            "tmdb_id": 438631,
            "folder": folder,
            "status": "released",
            "has_content": 1,
        },
        "movie",
        "radarr",
        instance,
    )


def _logos(db, dest):
    """What radarr1's and radarr2's Dune rows record, and dest's logo files by name."""
    ids = [db.media.get_by_instance(name)[0]["id"] for name in ("radarr1", "radarr2")]
    rows = [db.media_asset_matches.get_one("media", i, "logo") for i in ids]
    files = {p.name: p.read_bytes() for p in sorted(dest.iterdir())}
    names = [os.path.basename(r["applied_path"] or "") for r in rows]
    return [(r["match_status"], n) for r, n in zip(rows, names)], files


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_a_moved_logo_reaches_the_same_movie_in_another_instance(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = order
    m.run()
    rows, files = _logos(db, dest)
    two = "Dune (2021) {tmdb-438631}_logo.png"
    assert rows == [("applied", "Dune (2021)_logo.png"), ("applied", two)]
    assert files == {two: b"png", "Dune (2021)_logo.png": b"png"}
    assert list((tmp_path / "src").iterdir()) == []


def test_a_moved_logo_two_instances_place_at_one_path_is_applied_for_both(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _dune_in(db, "radarr2", "Dune (2021)")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    rows, files = _logos(db, dest)
    assert rows == [("applied", "Dune (2021)_logo.png")] * 2
    assert files == {"Dune (2021)_logo.png": b"png"}


def test_an_instance_that_adds_the_movie_after_a_move_gets_its_logo(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    rows, files = _logos(db, dest)
    two = "Dune (2021) {tmdb-438631}_logo.png"
    assert rows == [("applied", "Dune (2021)_logo.png"), ("applied", two)]
    assert files == {two: b"png", "Dune (2021)_logo.png": b"png"}


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_a_moved_logo_follows_its_folder_rename_and_reaches_an_instance_added_with_it(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    _dune_in(db, "radarr1", "Dune HD (2021)")
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = order
    m.run()
    rows, files = _logos(db, dest)
    two = "Dune (2021) {tmdb-438631}_logo.png"
    assert rows == [("applied", "Dune HD (2021)_logo.png"), ("applied", two)]
    assert files == {two: b"png", "Dune HD (2021)_logo.png": b"png"}


@pytest.mark.parametrize("restored", [False, True], ids=["pick-moved", "pick-restored"])
def test_a_logo_picked_for_one_instance_is_kept_beside_the_others(
    db, monkeypatch, tmp_path, restored
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    pick = tmp_path / "mine.png"
    pick.write_bytes(b"my pick")
    two_dune = db.media.get_by_instance("radarr2")[0]
    applied, detail = m.apply_chosen_asset(db, "media", two_dune, "logo", str(pick))
    assert (applied, pick.exists()) == (True, False), detail
    if restored:
        # As a sync brings it back: placed again, first, this run.
        pick.write_bytes(b"my pick")
    m.config.instances = ["radarr2", "radarr1"] if restored else ["radarr1", "radarr2"]
    m.run()
    rows, files = _logos(db, dest)
    two = "Dune (2021) {tmdb-438631}_logo.png"
    assert rows == [("applied", "Dune (2021)_logo.png"), ("applied", two)]
    assert files == {two: b"my pick", "Dune (2021)_logo.png": b"png"}


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_a_logo_picked_for_one_instance_does_not_reach_an_instance_with_none(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    pick = tmp_path / "mine.png"
    pick.write_bytes(b"my pick")
    one_dune = db.media.get_by_instance("radarr1")[0]
    applied, detail = m.apply_chosen_asset(db, "media", one_dune, "logo", str(pick))
    assert applied, detail
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = order
    m.run()
    rows, files = _logos(db, dest)
    assert rows == [("applied", "Dune (2021)_logo.png"), ("missing", "")]
    assert files == {"Dune (2021)_logo.png": b"my pick"}


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_a_logo_picked_during_a_run_does_not_reach_another_instance(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    pick = tmp_path / "mine.png"
    pick.write_bytes(b"my pick")
    one_dune = db.media.get_by_instance("radarr1")[0]
    two_dune = db.media.get_by_instance("radarr2")[0]
    real_sibling = AssetMoves.sibling

    def _sibling(moves, media, *a, **k):
        # The user picks radarr1's logo in the UI just before radarr2 is offered one.
        if media["id"] == two_dune["id"] and pick.exists():
            picker = make_module(destination_dir=str(dest), action_type="move")
            picked = picker.apply_chosen_asset(db, "media", one_dune, "logo", str(pick))
            assert picked[0], picked[1]
        return real_sibling(moves, media, *a, **k)

    monkeypatch.setattr(AssetMoves, "sibling", _sibling)
    m.config.instances = order
    m.run()
    rows, files = _logos(db, dest)
    assert rows == [("applied", "Dune (2021)_logo.png"), ("missing", "")]
    assert files == {"Dune (2021)_logo.png": b"my pick"}


def test_a_logo_picked_once_its_source_is_moved_does_not_reach_another_instance(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    pick = tmp_path / "mine.png"
    pick.write_bytes(b"my pick")
    one_dune = db.media.get_by_instance("radarr1")[0]
    real_replace = os.replace

    def _replace(src, dst, *a, **k):
        real_replace(src, dst, *a, **k)
        # The user picks radarr1's logo in the UI as soon as its source lands.
        if os.path.basename(dst) == "Dune (2021)_logo.png" and pick.exists():
            picker = make_module(destination_dir=str(dest), action_type="move")
            picked = picker.apply_chosen_asset(db, "media", one_dune, "logo", str(pick))
            assert picked[0], picked[1]

    monkeypatch.setattr(os, "replace", _replace)
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    rows, files = _logos(db, dest)
    assert rows == [("applied", "Dune (2021)_logo.png"), ("missing", "")]
    assert files == {"Dune (2021)_logo.png": b"my pick"}


def test_a_newer_sibling_logo_is_not_placed_over_a_pick_two_instances_share(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _dune_in(db, "radarr2", "Dune (2021)")
    _dune_in(db, "radarr3", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2", "radarr3"]
    m.run()
    pick = tmp_path / "mine.png"
    pick.write_bytes(b"my pick")
    os.utime(pick, (1_000_000_000, 1_000_000_000))  # older than the shared logo
    one_dune = db.media.get_by_instance("radarr1")[0]
    applied, detail = m.apply_chosen_asset(db, "media", one_dune, "logo", str(pick))
    assert applied, detail
    m.config.instances = ["radarr2", "radarr3", "radarr1"]
    m.run()
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == {
        "Dune (2021)_logo.png": b"my pick",
        "Dune (2021) {tmdb-438631}_logo.png": b"png",
    }


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_a_picked_logo_carried_to_a_renamed_folder_does_not_reach_another_instance(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.run()
    pick = tmp_path / "mine.png"
    pick.write_bytes(b"my pick")
    one_dune = db.media.get_by_instance("radarr1")[0]
    applied, detail = m.apply_chosen_asset(db, "media", one_dune, "logo", str(pick))
    assert applied, detail
    _dune_in(db, "radarr1", "Dune HD (2021)")
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = order
    m.run()
    rows, files = _logos(db, dest)
    assert rows == [("applied", "Dune HD (2021)_logo.png"), ("missing", "")]
    assert files == {"Dune HD (2021)_logo.png": b"my pick"}


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_an_adopted_logo_carried_to_a_renamed_folder_does_not_beat_a_newer_one(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _placed_files(tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    _dune_in(db, "radarr2", "Dune UHD (2021)")
    m.config.instances = ["radarr2"]
    m.run()
    new = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    new.write_bytes(b"new")
    os.utime(new, (1_500_000_000, 1_500_000_000))  # after the source, before the copy
    m.config.instances = ["radarr1"]
    m.run()
    m.config.instances = order
    m.run()
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == {
        "Dune (2021)_logo.png": b"new",
        "Dune UHD (2021)_logo.png": b"new",
    }


def test_a_logo_one_of_two_instances_at_one_path_updates_reaches_a_third(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _placed_files(tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021)")
    _dune_in(db, "radarr3", "Dune 4K (2021)")
    m.config.instances = ["radarr1", "radarr2", "radarr3"]
    m.run()
    new = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    new.write_bytes(b"new")
    os.utime(new, (1_500_000_000, 1_500_000_000))
    m.config.instances = ["radarr1"]
    m.run()
    m.config.instances = ["radarr1", "radarr2", "radarr3"]
    m.run()
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == {
        "Dune (2021)_logo.png": b"new",
        "Dune 4K (2021)_logo.png": b"new",
    }


def test_a_copied_logo_whose_source_was_deleted_is_not_spread_to_another_instance(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    m.run()
    for src in (tmp_path / "src").iterdir():
        src.unlink()
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    rows, files = _logos(db, dest)
    assert rows == [("applied", "Dune (2021)_logo.png"), ("missing", "")]
    assert files == {"Dune (2021)_logo.png": b"png"}


@pytest.mark.parametrize(
    "apply_method, action_type", [("plex", "move"), ("kometa", "copy")]
)
def test_only_a_move_to_kometa_shares_placed_logos(tmp_path, apply_method, action_type):
    placed = tmp_path / "Dune (2021)_logo.png"
    placed.write_bytes(b"png")
    dune = {"id": 1, "asset_type": "movie", "tmdb_id": 438631, "title": "Dune"}
    row = {"applied_method": "kometa", "applied_path": str(placed)}
    applied_map = {("media", 1, "logo"): row}
    off = make_module(apply_method=apply_method, action_type=action_type).config
    on = make_module(apply_method="kometa", action_type="move").config
    unused = AssetMoves.load(off, [dune], applied_map, ["logo"], lambda _p: False)
    found = AssetMoves.load(on, [dune], applied_map, ["logo"], lambda _p: False)
    assert (
        unused.sibling(dune, "logo", None, None),
        found.sibling(dune, "logo", None, None),
    ) == (None, ("local", str(placed), None))


def _dune_moves(tmp_path, recorded):
    """AssetMoves under move, loaded from Dune rows placed at (name, source_mtime)."""
    dunes = [
        {"id": i, "asset_type": "movie", "tmdb_id": 438631, "title": "Dune"}
        for i in range(1, len(recorded) + 1)
    ]
    applied_map = {}
    for dune, (name, mtime, *written) in zip(dunes, recorded):
        (tmp_path / name).write_bytes(b"png")
        row = {"applied_path": str(tmp_path / name), "source_mtime": mtime}
        row["matched_at"] = written[0] if written else None
        applied_map[("media", dune["id"], "logo")] = row
    config = make_module(apply_method="kometa", action_type="move").config
    moves = AssetMoves.load(config, dunes, applied_map, ["logo"], lambda _p: False)
    return moves, dunes


@pytest.mark.parametrize(
    "source, held",
    [(None, True), ("gone.png", True), ("back.png", False)],
    ids=["downloaded", "moved-away", "saved-again"],
)
def test_a_copy_of_a_deselected_items_logo_traces_back_to_its_source(
    tmp_path, source, held
):
    placed_a, placed_b = tmp_path / "a.png", tmp_path / "b.png"
    for p in (placed_a, placed_b, tmp_path / "back.png"):
        p.write_bytes(b"png")
    a_from = source and str(tmp_path / source)
    a = {"applied_path": str(placed_a), "matched_file": a_from}
    b = {"applied_path": str(placed_b), "matched_file": str(placed_a)}
    applied_map = {("media", 1, "logo"): a, ("media", 2, "logo"): b}
    dune = {"id": 2, "asset_type": "movie", "tmdb_id": 438631, "title": "Dune"}
    config = make_module(apply_method="kometa", action_type="move").config
    moves = AssetMoves.load(config, [dune], applied_map, ["logo"], lambda _p: False)
    assert moves.held(dune, "logo") is held


def test_a_path_placed_again_with_older_art_is_not_offered_as_newer(tmp_path):
    moves, (one, two) = _dune_moves(tmp_path, [("a.png", 200), ("b.png", 150)])
    moves.add(one, "logo", str(tmp_path / "a.png"), mtime=100)
    assert moves.sibling(two, "logo", str(tmp_path / "b.png"), 150) is None


@pytest.mark.parametrize("later_row_first", [False, True])
@pytest.mark.parametrize("own_mtime, offered", [(150, False), (50, True)])
def test_a_shared_path_rewritten_with_older_art_keeps_the_later_writes_time(
    tmp_path, later_row_first, own_mtime, offered
):
    first = ("a.png", 200, "2026-11-19T10:00:00+00:00")
    later = ("a.png", 100, "2026-11-19T11:00:00.500000+00:00")
    rows = [later, first] if later_row_first else [first, later]
    moves, (*_, three) = _dune_moves(tmp_path, [*rows, ("c.png", own_mtime)])
    got = moves.sibling(three, "logo", str(tmp_path / "c.png"), own_mtime)
    assert got == (("local", str(tmp_path / "a.png"), None) if offered else None)


def test_a_moved_source_whose_placed_file_is_gone_is_not_offered(tmp_path):
    moves, (dune,) = _dune_moves(tmp_path, [("a.png", 100)])
    placed, source = tmp_path / "b.png", str(tmp_path / "src.png")
    placed.write_bytes(b"png")
    moves.add(dune, "logo", str(placed), source=source, mtime=100)
    assert moves.went(source) == str(placed)
    placed.unlink()
    assert moves.went(source) is None


def test_an_own_path_another_row_updated_is_not_offered_back(tmp_path):
    moves, (_one, two) = _dune_moves(tmp_path, [("a.png", 200), ("a.png", 100)])
    assert moves.sibling(two, "logo", str(tmp_path / "a.png"), 100) is None


@pytest.mark.parametrize(
    "asset_type, season, image_type, method, skipped",
    [
        ("show", 1, "logo", "kometa", True),
        ("show", 0, "logo", "plex", True),
        ("show", None, "logo", "kometa", False),
        ("album", None, "logo", "plex", True),
        ("artist", None, "logo", "plex", False),
        ("show", 1, "squareart", "kometa", True),
        ("show", 0, "squareart", "kometa", True),
        ("show", 1, "squareart", "plex", False),
        ("show", None, "squareart", "kometa", False),
        ("show", 1, "background", "kometa", False),
    ],
)
def test_art_no_provider_publishes_or_kometa_reads_is_skipped(
    asset_type, season, image_type, method, skipped
):
    media = {"asset_type": asset_type, "season_number": season}
    assert AssetRenamerr._never_applies(media, image_type, method) is skipped


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_a_new_logo_for_a_movie_two_instances_share_reaches_both(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = order
    m.run()
    new = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    new.write_bytes(b"new")
    os.utime(new, (2_000_000_000, 2_000_000_000))
    m.run()
    rows, files = _logos(db, dest)
    two = "Dune (2021) {tmdb-438631}_logo.png"
    assert rows == [("applied", "Dune (2021)_logo.png"), ("applied", two)]
    assert files == {two: b"new", "Dune (2021)_logo.png": b"new"}


@pytest.mark.parametrize("order", [["radarr1", "radarr2"], ["radarr2", "radarr1"]])
def test_each_instance_gets_the_first_choice_logo_and_the_next_stays(
    db, monkeypatch, tmp_path, order
):
    dest, src2 = tmp_path / "kometa", tmp_path / "src2"
    dest.mkdir()
    src2.mkdir()
    (src2 / "Dune (2021) {tmdb-438631} - Logo.png").write_bytes(b"runner-up")
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.config.source_dirs.insert(0, str(src2))  # bottom-wins: src2 ranks below src
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = order
    m.run()
    rows, files = _logos(db, dest)
    two = "Dune (2021) {tmdb-438631}_logo.png"
    assert rows == [("applied", "Dune (2021)_logo.png"), ("applied", two)]
    assert files == {two: b"png", "Dune (2021)_logo.png": b"png"}
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]


@pytest.mark.parametrize(
    "order", [["radarr1", "radarr2", "radarr3"], ["radarr3", "radarr2", "radarr1"]]
)
def test_a_newer_logo_reaches_the_instances_a_run_missed(
    db, monkeypatch, tmp_path, order
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    new = tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png"
    new.write_bytes(b"new")
    os.utime(new, (2_000_000_000, 2_000_000_000))
    m.config.instances = ["radarr1"]
    m.run()
    _dune_in(db, "radarr3", "Dune 4K (2021)")
    m.config.instances = order
    m.run()
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == {
        "Dune (2021)_logo.png": b"new",
        "Dune (2021) {tmdb-438631}_logo.png": b"new",
        "Dune 4K (2021)_logo.png": b"new",
    }


def _placed_files(tmp_path, dest):
    """Date the sources well before any run; returns dest's files as (inode, mtime)."""
    for src in (tmp_path / "src").iterdir():
        os.utime(src, (1_000_000_000, 1_000_000_000))
    return lambda: {
        p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in sorted(dest.iterdir())
    }


def test_logos_one_instance_adopted_from_another_are_not_rewritten_by_later_runs(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    files = _placed_files(tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    _dune_in(db, "radarr3", "Dune 4K (2021)")
    m.config.instances = ["radarr2", "radarr1", "radarr3"]
    m.run()
    placed = files()
    for _ in range(3):
        m.run()
    assert (len(placed), files()) == (3, placed)


def test_logos_copied_then_shared_under_move_are_not_rewritten_by_later_runs(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m = _standalone_run(db, monkeypatch, tmp_path, dest)
    files = _placed_files(tmp_path, dest)
    m.run()
    for src in (tmp_path / "src").iterdir():
        src.unlink()
    m.config.action_type = "move"
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    placed = files()
    m.run()
    assert (len(placed), files()) == (2, placed)


def _with_runner_up(db, monkeypatch, tmp_path, dest):
    """A move run whose src2 holds a Dune logo ranked below src's."""
    src2 = tmp_path / "src2"
    src2.mkdir()
    (src2 / "Dune (2021) {tmdb-438631} - Logo.png").write_bytes(b"runner-up")
    m = _standalone_run(db, monkeypatch, tmp_path, dest, action_type="move")
    m.config.source_dirs.insert(0, str(src2))  # bottom-wins: src2 ranks below src
    return m, src2


@pytest.mark.parametrize(
    "instances", [["radarr1"], ["radarr1", "radarr2"], ["radarr2", "radarr1"]]
)
def test_a_moved_first_choice_logo_is_not_replaced_by_the_runner_up_later(
    db, monkeypatch, tmp_path, instances
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = instances
    for _ in range(2):
        m.run()
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"png"] * len(instances)
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]


def test_an_instance_added_after_the_first_choice_moved_gets_it_not_the_runner_up(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    m.run()
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    for _ in range(2):
        m.run()
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"png", b"png"]
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]


@pytest.mark.parametrize("instances", [["radarr1"], ["radarr1", "radarr2"]])
def test_the_runner_up_is_placed_once_every_moved_first_choice_is_deleted(
    db, monkeypatch, tmp_path, instances
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = instances
    m.run()
    for p in dest.iterdir():
        p.unlink()
    m.run()
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"runner-up"] * len(
        instances
    )


def test_a_moved_first_choice_deleted_for_one_instance_is_restored_from_the_other(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    (dest / "Dune (2021)_logo.png").unlink()
    m.run()
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"png", b"png"]
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]


@pytest.mark.parametrize("kept", ["radarr1", "radarr2"])
def test_a_moved_first_choice_stays_when_the_other_instance_is_deselected(
    db, monkeypatch, tmp_path, kept
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    m.config.instances = [kept]
    for _ in range(2):
        m.run()
    assert sorted(p.read_bytes() for p in dest.iterdir()) == [b"png", b"png"]
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]


@pytest.mark.parametrize(
    "kept, logo",
    [
        ("radarr1", "Dune (2021)_logo.png"),
        ("radarr2", "Dune (2021) {tmdb-438631}_logo.png"),
    ],
)
def test_a_source_saved_again_reaches_an_instance_whose_sibling_is_deselected(
    db, monkeypatch, tmp_path, kept, logo
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    _dune_in(db, "radarr2", "Dune (2021) {tmdb-438631}")
    m.config.instances = ["radarr1", "radarr2"]
    m.run()
    m.config.instances = [kept]
    (tmp_path / "src" / "Dune (2021) {tmdb-438631} - Logo.png").write_bytes(b"new")
    for _ in range(2):
        m.run()
    assert (dest / logo).read_bytes() == b"new"
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]


def test_a_moved_first_choice_logo_follows_a_folder_rename_over_the_runner_up(
    db, monkeypatch, tmp_path
):
    dest = tmp_path / "kometa"
    dest.mkdir()
    m, src2 = _with_runner_up(db, monkeypatch, tmp_path, dest)
    m.run()
    _dune_in(db, "radarr1", "Dune HD (2021)")
    for _ in range(2):
        m.run()
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == {
        "Dune HD (2021)_logo.png": b"png"
    }
    assert [p.read_bytes() for p in src2.iterdir()] == [b"runner-up"]
