"""Pins Upgradinatorr's per-run limits through the real process_instance: the
max-grabs cap and the minimum release age."""

from types import SimpleNamespace

import pytest

import backend.modules.upgradinatorr as upgradinatorr_module
from backend.util.config import UpgradinatorrInstance
from backend.util.upgradinatorr_notification import build_upgradinatorr_embeds

from tests.test_config import FakeARR, make_upgradinatorr


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """process_instance opens its own ChubDB; keep it out of config/chub.db."""
    path = str(tmp_path / "chub.db")
    real = upgradinatorr_module.ChubDB
    monkeypatch.setattr(
        upgradinatorr_module, "ChubDB", lambda **kwargs: real(db_path=path, **kwargs)
    )
    return path


def _movie(media_id, **overrides):
    item = {
        "title": f"Movie {media_id}",
        "year": 2001,
        "media_id": media_id,
        "monitored": True,
        "status": "released",
        "seasons": None,
        "tags": [],
    }
    item.update(overrides)
    return item


class _GrabbingARR(FakeARR):
    """Each searched movie in ``grabs_for`` shows one grab in its history afterwards."""

    history_import_event = 3
    history_upgrade_delete_event = 6
    history_failed_event = 4
    upgrade_pair_field = "movieId"

    def __init__(self, movies, grabs_for=None):
        super().__init__([movies])
        self.searched = []
        ids = [movie["media_id"] for movie in movies]
        self.grabs_for = set(ids if grabs_for is None else grabs_for)

    def search_media(self, media_id):
        self.searched.append(media_id)
        return super().search_media(media_id)

    def get_grab_history(self, media_id):
        if media_id not in self.searched or media_id not in self.grabs_for:
            return []
        return [
            {
                "downloadId": f"dl-{media_id}",
                "movieId": media_id,
                "sourceTitle": f"Movie.{media_id}-GRP",
                "customFormatScore": 100,
                "eventType": "grabbed",
            }
        ]

    def get_history_since(self, date, event_type):
        return []


def _settings(**overrides):
    base = dict(
        count=10,
        tag_name="checked",
        ignore_tag="ignore",
        unattended=False,
        season_monitored_threshold=0,
        search_mode="upgrade",
        queue_block_hours=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_the_run_stops_once_max_grabs_items_have_grabbed(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _GrabbingARR([_movie(1), _movie(2), _movie(3), _movie(4)], grabs_for={1, 3})

    result = module.process_instance("radarr", _settings(max_grabs=2), app)

    # Movie 2 searched and grabbed nothing, so the cap is met only after movie 3.
    assert app.searched == [1, 2, 3]
    assert [media_id for media_id, _tag in app.add_calls] == [1, 2, 3]
    assert result["max_grabs_hit"] == 2
    [part] = build_upgradinatorr_embeds({"radarr": result})
    assert (
        "Max grabs 2 reached: stopped early, the rest is searched next run"
        in part["description"]
    )


@pytest.mark.parametrize("cap", [0, None, "junk", -1, True])
def test_no_usable_cap_searches_the_whole_batch(isolated_db, cap):
    module = make_upgradinatorr(dry_run=False)
    app = _GrabbingARR([_movie(1), _movie(2), _movie(3)])

    result = module.process_instance("radarr", _settings(max_grabs=cap), app)

    assert app.searched == [1, 2, 3]
    assert "max_grabs_hit" not in result


def test_the_config_keeps_max_grabs_and_defaults_it_off():
    assert UpgradinatorrInstance().max_grabs == 0
    assert UpgradinatorrInstance(max_grabs=3).max_grabs == 3
