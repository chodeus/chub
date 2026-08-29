"""Regression tests for SyncGDrive._refresh_poster_cache_for_folder.

A gdrive_list folder that lives outside every renamer source_dir must be
re-indexed as search_only=1 (findable in Assets Search, excluded from
matching) WITHOUT raising. Guards the unbound-`priority` bug on the
search-only path: the trailing log line referenced `priority`, which was
only assigned on the owned branch, so syncing an "Extras" drive threw
"cannot access local variable 'priority'" and indexed zero rows.
"""

import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


class _StubPosterRenamerr:
    """Stand-in PosterRenamerr with no source_dirs (so any folder is
    non-owned). _get_assets_files echoes back the search_only flag it's
    handed, so the test verifies the refresh passes search_only=1 on the
    gdrive-only path."""

    def __init__(self, logger=None):
        self.logger = logger
        self.config = SimpleNamespace(source_dirs=[], run_asset_renamerr=False)
        self.full_config = SimpleNamespace(
            asset_renamerr=SimpleNamespace(source_dirs=[])
        )

    def _matchable_source_dirs(self):
        return []

    def _get_assets_files(
        self, source_dir, priority=0, include_assets=False, search_only=0
    ):
        return [
            {
                "title": "Extras Logo Movie",
                "normalized_title": "extraslogomovie",
                "year": 2023,
                "tmdb_id": None,
                "tvdb_id": None,
                "imdb_id": None,
                "season_number": None,
                "folder": os.path.basename(source_dir.rstrip("/")),
                "file": os.path.join(
                    source_dir, "Extras Logo Movie (2023) - Logo.png"
                ),
                "style": None,
                "priority": priority,
                "image_type": "logo",
                "asset_type": "movie",
                "search_only": search_only,
            }
        ]


def test_refresh_marks_gdrive_only_folder_search_only(monkeypatch):
    import backend.modules.poster_renamerr as pr_mod

    monkeypatch.setattr(pr_mod, "PosterRenamerr", _StubPosterRenamerr)

    from backend.modules.sync_gdrive import SyncGDrive

    with tempfile.TemporaryDirectory() as tmp:
        loc = os.path.join(tmp, "Extras", "Tarantula212")
        os.makedirs(loc)
        with ChubDB(_logger(), db_path=os.path.join(tmp, "chub.db")) as db:
            # Capture logger.error: the bug threw UnboundLocalError at the
            # trailing log line, which the method's try/except swallowed and
            # logged. The upserts ran *before* the throw, so only an
            # error-was-logged check distinguishes the buggy path.
            errors = []
            log = _logger()
            log.error = lambda *a, **k: errors.append(a)

            sg = object.__new__(SyncGDrive)
            sg.logger = log
            sg.db = db

            sg._refresh_poster_cache_for_folder(loc)

            # Regression: no swallowed UnboundLocalError on the search-only path.
            assert errors == []

            # Indexed as a search-only logo row...
            artwork = db.poster.browse(image_type="artwork")["items"]
            assert len(artwork) == 1
            assert artwork[0]["search_only"] == 1
            assert artwork[0]["image_type"] == "logo"

            # ...and excluded from matching.
            assert (
                db.poster.get_by_normalized_title(
                    "extraslogomovie", image_type="logo"
                )
                is None
            )


# --- uses_shared_rclone_client_id ---


def _sync_cfg(sa="", client_id=""):
    return SimpleNamespace(gdrive_sa_location=sa, client_id=client_id)


def test_shared_client_id_used_when_neither_auth_method_is_set():
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    assert uses_shared_rclone_client_id(_sync_cfg()) is True


def test_service_account_bypasses_the_shared_client_id(tmp_path):
    """An SA authenticates with its own key — no OAuth client is involved."""
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    sa = tmp_path / "sa.json"
    sa.write_text("{}")
    assert uses_shared_rclone_client_id(_sync_cfg(sa=str(sa))) is False


def test_missing_sa_file_still_counts_as_the_shared_client_id(tmp_path):
    """run() nulls a missing SA path and falls through to OAuth, so this warns."""
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    missing = str(tmp_path / "nope.json")
    assert uses_shared_rclone_client_id(_sync_cfg(sa=missing)) is True
    assert uses_shared_rclone_client_id(_sync_cfg(sa=missing, client_id="mine")) is False


def test_sa_path_pointing_at_a_directory_is_not_credentials(tmp_path):
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    assert uses_shared_rclone_client_id(_sync_cfg(sa=str(tmp_path))) is True


def test_own_client_id_bypasses_the_shared_one():
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    assert uses_shared_rclone_client_id(_sync_cfg(client_id="my-own.apps.google")) is False


def test_whitespace_only_credentials_still_count_as_unset():
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    assert uses_shared_rclone_client_id(_sync_cfg(sa="  ", client_id="  ")) is True


def test_missing_attributes_are_treated_as_unset():
    """An older config object may not carry the fields at all."""
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    assert uses_shared_rclone_client_id(SimpleNamespace()) is True
