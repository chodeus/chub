"""Pins the per-run limits (max grabs, minimum release age) through process_instance."""

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
        "Max Items Grabbed Per Run reached: 2 movies grabbed something, "
        "the rest is searched next run"
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


def _days_ago(days):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


def test_items_inside_the_minimum_age_are_held_back(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    movies = [
        _movie(1, release_date=_days_ago(5)),
        _movie(2, release_date=_days_ago(60)),
        _movie(3, release_date=None),
        _movie(4, release_date=_days_ago(30)),
    ]
    app = _GrabbingARR(movies)

    result = module.process_instance("radarr", _settings(min_age_days=30), app)

    # Released exactly 30 days ago is old enough; no date can't be shown old enough.
    assert app.searched == [2, 4]
    assert result["release_holds"] == {"days": 30, "too_new": 1, "no_date": 1}
    [part] = build_upgradinatorr_embeds({"radarr": result})
    assert (
        "Held back: 1 movie released in the last 30 days, 1 movie with no release date"
        in part["description"]
    )


def test_without_a_minimum_age_nothing_is_held(isolated_db):
    module = make_upgradinatorr(dry_run=False)
    app = _GrabbingARR([_movie(1, release_date=_days_ago(1)), _movie(2)])

    result = module.process_instance("radarr", _settings(), app)

    assert app.searched == [1, 2]
    assert "release_holds" not in result


def test_a_held_item_does_not_stop_the_rotation_from_starting_over(isolated_db):
    """Held items sit outside the pool, so the unattended reset still fires."""
    module = make_upgradinatorr(dry_run=False)
    first = [
        _movie(1, release_date=_days_ago(90), tags=["checked"]),
        _movie(2, release_date=_days_ago(2)),
    ]
    reset = [_movie(1, release_date=_days_ago(90)), _movie(2, release_date=_days_ago(2))]
    app = _GrabbingARR(first)
    app.media_batches = [first, reset]

    module.process_instance(
        "radarr", _settings(min_age_days=30, unattended=True), app
    )

    assert app.remove_calls == [([1, 2], 1)]
    assert app.searched == [1]


def test_lidarr_holds_each_new_album_rather_than_the_artist():
    module = make_upgradinatorr(dry_run=False)
    artist = {
        "title": "Artist",
        "monitored": True,
        "seasons": [
            {"album_id": 1, "monitored": True, "release_date": _days_ago(400)},
            {"album_id": 2, "monitored": True, "release_date": _days_ago(3)},
            {"album_id": 3, "monitored": False, "release_date": _days_ago(3)},
        ],
    }

    holds = module._hold_new_releases([artist], "lidarr", 30)

    assert holds == {"too_new": 1, "no_date": 0}
    assert [album["monitored"] for album in artist["seasons"]] == [True, False, False]
    assert "release_hold" not in artist


def test_lidarr_wanted_albums_carry_their_release_date():
    module = make_upgradinatorr(dry_run=False)
    app = SimpleNamespace(get_all_tags=lambda: [])
    wanted = [
        {
            "id": 31,
            "title": "Album",
            "releaseDate": "2004-01-01T00:00:00Z",
            "artist": {"id": 5, "artistName": "Artist", "monitored": True, "path": "/music/Artist"},
        }
    ]

    [artist] = module._convert_wanted_to_media_dict(wanted, "lidarr", app)

    assert artist["seasons"][0]["release_date"] == "2004-01-01"


def test_the_config_keeps_min_age_days_and_defaults_it_off():
    assert UpgradinatorrInstance().min_age_days == 0
    assert UpgradinatorrInstance(min_age_days=30).min_age_days == 30
