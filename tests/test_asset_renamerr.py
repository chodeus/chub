"""Tests for backend/modules/asset_renamerr.py and the shared asset plumbing.

Covers:
* build_asset_record() image_type detection + suffix stripping (incl. the real
  g-drive filename convention and negative cases).
* image_type filtering keeps poster matching isolated from asset rows.
* source-priority resolution (local vs fanart, first match wins).
* the apply dispatcher (banner skipped on the direct path; correct PlexClient
  method called otherwise) and the Kometa rename path.
"""

import os
from types import SimpleNamespace

import pytest

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


def _seed(db, image_type, fname):
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
            "file": f"/x/{fname}",
            "style": None,
            "priority": 0,
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
        with pytest.raises(Exception):
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


def test_source_priority_local_first(db):
    _seed(db, "logo", "8 A.M. Metro (2023) - Logo.png")
    m = make_module(sources=["local", "fanart"])
    src, file, url = m._resolve_source(_media(), db, "logo", False, _fake_fanart())
    assert src == "local" and file and url is None


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


def test_kometa_requires_destination():
    m = make_module(apply_method="kometa", destination_dir="")
    applied, reason = m._apply_kometa(_media(), "logo", "local", "/x/l.png", None)
    assert applied is False and "destination" in reason.lower()


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
