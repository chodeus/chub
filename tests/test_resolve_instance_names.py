"""Listed instance names resolve to configured ones; leftovers are dropped, removed ones refused."""

from types import SimpleNamespace

import pytest

from backend.util.config import ChubConfig, InstanceDetail
from backend.util.connector import resolve_instance_names
from backend.util.database import ChubDB


def _logger():
    warned = []
    noop = lambda *a, **k: None  # noqa: E731
    return SimpleNamespace(
        warned=warned,
        warning=lambda msg, *a, **k: warned.append(msg),
        info=noop,
        debug=noop,
        error=noop,
        get_adapter=lambda *a, **k: SimpleNamespace(
            info=noop, debug=noop, warning=noop, error=noop
        ),
    )


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


@pytest.fixture
def configured(monkeypatch):
    """Radarr, Radarr4k and Sonarr configured, as a rename to capitals leaves them."""
    cfg = ChubConfig()
    for name in ("Radarr", "Radarr4k"):
        cfg.instances.radarr[name] = InstanceDetail(url="http://r:7878", api="k")
    cfg.instances.sonarr["Sonarr"] = InstanceDetail(url="http://s:8989", api="k")
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    return cfg


def _seed_media(db, instance_name):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "asset_type) VALUES (?,?,?,?)",
        (f"k-{instance_name}", instance_name, "sometitle", "movie"),
    )


def test_names_differing_only_in_case_resolve_to_the_configured_ones(db, configured):
    listed = ["Radarr", "Radarr4k", "Sonarr", "radarr", "radarr4k", "sonarr"]

    names, refusal = resolve_instance_names(db, _logger(), listed, "the scan")

    assert (names, refusal) == (["Radarr", "Radarr4k", "Sonarr"], None)


def test_a_leftover_name_with_nothing_cached_is_dropped_with_a_warning(db, configured):
    log = _logger()

    names, refusal = resolve_instance_names(db, log, ["Radarr", "oldradarr"], "the scan")

    assert (names, refusal) == (["Radarr"], None)
    assert len(log.warned) == 1 and "oldradarr" in log.warned[0]


def test_a_removed_instance_with_cached_media_is_refused_by_name(db, configured):
    _seed_media(db, "oldradarr")

    names, refusal = resolve_instance_names(db, _logger(), ["Radarr", "oldradarr"], "the scan")

    assert names == []
    assert "oldradarr" in refusal and "Remove it from that list in Settings" in refusal


def test_a_removed_instance_with_cached_collections_is_refused(db, configured):
    db.collection.upsert({"title": "Some Saga", "library_name": "Films"}, "oldplex")

    names, refusal = resolve_instance_names(db, _logger(), ["Radarr", "oldplex"], "the scan")

    assert names == [] and "oldplex" in refusal


def test_nothing_left_is_refused(db, configured):
    names, refusal = resolve_instance_names(db, _logger(), ["gone1", "gone2"], "the scan")

    assert names == [] and "None of the instances" in refusal


def test_an_empty_list_stays_empty(db, configured):
    result = resolve_instance_names(db, _logger(), [], "the scan")

    assert result == ([], None)


def test_an_ambiguous_case_match_is_refused_even_beside_a_valid_name(db, configured):
    configured.instances.radarr["RADARR"] = InstanceDetail(url="http://r2:7878", api="k")

    names, refusal = resolve_instance_names(db, _logger(), ["Sonarr", "radarr"], "the scan")

    assert names == []
    assert "matches more than one" in refusal and "RADARR" in refusal


def test_an_exact_name_wins_over_case_variants(db, configured):
    configured.instances.radarr["RADARR"] = InstanceDetail(url="http://r2:7878", api="k")

    names, refusal = resolve_instance_names(db, _logger(), ["RADARR"], "the scan")

    assert (names, refusal) == (["RADARR"], None)


def test_an_unreadable_config_is_refused(db, monkeypatch):
    def boom():
        raise OSError("config.yml unreadable")

    monkeypatch.setattr("backend.util.config.load_config", boom)

    names, refusal = resolve_instance_names(db, _logger(), ["Radarr"], "the scan")

    assert names == [] and "Cannot load the config" in refusal


def test_a_name_shared_by_two_kinds_still_resolves_by_case(db, configured):
    configured.instances.plex["Radarr"] = InstanceDetail(url="http://p:32400", api="k")

    names, refusal = resolve_instance_names(db, _logger(), ["radarr"], "the scan")

    assert (names, refusal) == (["Radarr"], None)


def test_a_cache_lookup_error_is_a_refusal(configured):
    def boom(name):
        raise RuntimeError("database is locked")

    db = SimpleNamespace(
        media=SimpleNamespace(count_by_instance=boom),
        collection=SimpleNamespace(get_by_instance=boom),
    )

    names, refusal = resolve_instance_names(db, _logger(), ["Radarr", "oldradarr"], "the scan")

    assert names == [] and "database is locked" in refusal

