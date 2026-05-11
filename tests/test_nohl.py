from types import SimpleNamespace

import pytest

from backend.modules.nohl import Nohl
from backend.util.config import NohlConfig, NohlSourceDir
from backend.util.helper import normalize_titles


class CapturingLogger:
    def __init__(self):
        self.records = []

    def debug(self, message, *args, **kwargs):
        self.records.append(("debug", str(message)))

    def info(self, message, *args, **kwargs):
        self.records.append(("info", str(message)))

    def warning(self, message, *args, **kwargs):
        self.records.append(("warning", str(message)))

    def error(self, message, *args, **kwargs):
        self.records.append(("error", str(message)))


class FakeArrApp:
    def __init__(self, quality_profiles=None):
        self.quality_profiles = quality_profiles or {}

    def get_quality_profile_names(self):
        return self.quality_profiles


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("video")
    return path


def media_item(title, year=2024, root_folder="/media/tv", seasons=None):
    return {
        "media_id": 10,
        "title": title,
        "year": year,
        "secondary_year": None,
        "normalized_title": normalize_titles(title),
        "normalized_folder": normalize_titles(title),
        "normalized_alternate_titles": [],
        "root_folder": root_folder,
        "monitored": True,
        "quality_profile": 1,
        "seasons": seasons or [],
    }


def test_parse_source_entries_defaults_blank_modes_to_resolve():
    config = NohlConfig(
        source_dirs=[
            "/media/legacy",
            NohlSourceDir(path="/media/blank", mode=""),
            {"path": "/media/scan", "mode": "scan"},
        ]
    )

    scan_entries, resolve_entries = Nohl.parse_source_entries(config)

    assert scan_entries == [{"path": "/media/scan", "mode": "scan"}]
    assert resolve_entries == [
        {"path": "/media/legacy", "mode": "resolve"},
        {"path": "/media/blank", "mode": "resolve"},
    ]


def test_parse_source_entries_rejects_invalid_modes():
    config = NohlConfig(source_dirs=[{"path": "/media", "mode": "both"}])

    with pytest.raises(ValueError, match="Invalid Nohl source directory mode"):
        Nohl.parse_source_entries(config)


def test_find_nohl_files_keeps_movie_with_extra_subfolders_as_movie(tmp_path):
    logger = CapturingLogger()
    root = tmp_path / "movies"
    movie_dir = root / "Example Movie (2024)"
    touch(movie_dir / "Example Movie (2024).mkv")
    (movie_dir / "Featurettes").mkdir(parents=True)

    results = Nohl.find_nohl_files(str(root), logger)

    assert [item["title"] for item in results["movies"]] == ["Example Movie"]
    assert results["movies"][0]["year"] == 2024
    assert results["movies"][0]["nohl"] == [
        str(movie_dir / "Example Movie (2024).mkv")
    ]
    assert results["series"] == []


def test_find_nohl_files_groups_flat_episode_files_as_series(tmp_path):
    logger = CapturingLogger()
    root = tmp_path / "tv"
    show_dir = root / "Example Show"
    touch(show_dir / "Example.Show.S01E02.mkv")

    results = Nohl.find_nohl_files(str(root), logger)

    assert results["movies"] == []
    assert [item["title"] for item in results["series"]] == ["Example Show"]
    assert results["series"][0]["season_info"] == [
        {
            "season_number": 1,
            "episodes": [2],
            "season_pack": False,
            "nohl": [str(show_dir / "Example.Show.S01E02.mkv")],
        }
    ]


def test_find_nohl_files_skips_files_that_already_have_hardlinks(tmp_path):
    logger = CapturingLogger()
    root = tmp_path / "movies"
    movie_dir = root / "Already Linked (2024)"
    source = touch(movie_dir / "Already Linked (2024).mkv")
    source.link_to(movie_dir / "Already Linked (2024).copy.mkv")

    results = Nohl.find_nohl_files(str(root), logger)

    assert results == {"movies": [], "series": []}


def test_filter_media_searches_only_matching_sonarr_episodes():
    logger = CapturingLogger()
    config = SimpleNamespace(
        searches=10,
        exclude_profiles=[],
        exclude_movies=[],
        exclude_series=[],
    )
    seasons = [
        {
            "season_number": 1,
            "monitored": True,
            "episode_data": [
                {
                    "episode_number": 1,
                    "episode_id": 101,
                    "episode_file_id": 201,
                    "monitored": True,
                },
                {
                    "episode_number": 2,
                    "episode_id": 102,
                    "episode_file_id": 202,
                    "monitored": True,
                },
            ],
        }
    ]
    nohl_data = [
        {
            "title": "Example Show",
            "year": 2024,
            "normalized_title": normalize_titles("Example Show"),
            "root_path": "media/tv",
            "path": "/media/tv/Example Show",
            "season_info": [
                {
                    "season_number": 1,
                    "episodes": [2],
                    "season_pack": False,
                    "nohl": ["/media/tv/Example Show/Example.Show.S01E02.mkv"],
                }
            ],
        }
    ]

    filtered = Nohl.filter_media(
        FakeArrApp(),
        [media_item("Example Show", seasons=seasons)],
        nohl_data,
        "sonarr",
        config,
        logger,
    )

    assert filtered["filtered_media"] == []
    assert filtered["search_media"][0]["seasons"] == [
        {
            "season_number": 1,
            "season_pack": False,
            "episode_data": [
                {
                    "episode_number": 2,
                    "episode_id": 102,
                    "episode_file_id": 202,
                    "monitored": True,
                }
            ],
        }
    ]


def test_filter_media_skips_missing_movie_file_ids():
    logger = CapturingLogger()
    config = SimpleNamespace(
        searches=10,
        exclude_profiles=[],
        exclude_movies=[],
        exclude_series=[],
    )
    media = {
        "media_id": 7,
        "title": "Example Movie",
        "year": 2024,
        "secondary_year": None,
        "normalized_title": normalize_titles("Example Movie"),
        "normalized_folder": normalize_titles("Example Movie"),
        "normalized_alternate_titles": [],
        "root_folder": "/media/movies",
        "monitored": True,
        "quality_profile": 1,
        "file_id": None,
    }
    nohl_data = [
        {
            "title": "Example Movie",
            "year": 2024,
            "normalized_title": normalize_titles("Example Movie"),
            "root_path": "media/movies",
            "path": "/media/movies/Example Movie",
            "nohl": ["/media/movies/Example Movie/Example Movie.mkv"],
        }
    ]

    filtered = Nohl.filter_media(
        FakeArrApp(), [media], nohl_data, "radarr", config, logger
    )

    assert filtered["search_media"] == []
    assert filtered["filtered_media"] == [
        {
            "title": "Example Movie",
            "year": 2024,
            "monitored": True,
            "excluded": False,
            "quality_profile": None,
            "missing_file_id": True,
        }
    ]


def test_sonarr_search_limit_counts_seasons_not_series():
    logger = CapturingLogger()
    data_list = {
        "search_media": [
            {
                "title": "Show One",
                "seasons": [
                    {"season_number": 1},
                    {"season_number": 2},
                ],
            },
            {
                "title": "Show Two",
                "seasons": [
                    {"season_number": 1},
                ],
            },
        ]
    }

    Nohl._apply_search_limit(data_list, 2, "sonarr", logger)

    assert data_list["search_media"] == [
        {
            "title": "Show One",
            "seasons": [
                {"season_number": 1},
                {"season_number": 2},
            ],
        }
    ]
