"""CL2K asset makers accept a title with no TMDB id.

These endpoints render SUPPLIED art (backdrop_b64 / backdrop_path) and never call
list_images, so an id is only ever a filename tag. A TVDB- or IMDB-only title is
legitimate; only a title with NO id at all is rejected, because the filename
would carry nothing for CHUB or Kometa to match against.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api.cl2k_maker import (  # noqa: E402
    BackgroundArtRequest,
    LogoAssetRequest,
    SquareArtRequest,
    _require_any_id,
)
from backend.util.cl2k.naming import build_poster_filename  # noqa: E402

MODELS = [SquareArtRequest, LogoAssetRequest, BackgroundArtRequest]


@pytest.mark.parametrize("model", MODELS)
def test_model_accepts_a_tvdb_only_title(model):
    req = model(kind="show", title="Obscure Show", tvdb_id=479037)
    assert req.tmdb_id is None
    assert req.tvdb_id == 479037


@pytest.mark.parametrize("model", MODELS)
def test_model_accepts_an_imdb_only_title(model):
    req = model(kind="movie", title="Obscure Film", imdb_id="tt1234567")
    assert req.tmdb_id is None


@pytest.mark.parametrize("model", MODELS)
def test_guard_passes_with_any_single_id(model):
    for kwargs in ({"tmdb_id": 5}, {"tvdb_id": 5}, {"imdb_id": "tt1"}):
        req = model(kind="movie", title="X", **kwargs)
        assert _require_any_id(req) is None, kwargs


@pytest.mark.parametrize("model", MODELS)
def test_guard_rejects_a_title_with_no_id_at_all(model):
    req = model(kind="movie", title="X")
    resp = _require_any_id(req)
    assert resp is not None
    assert resp.status_code == 400
    assert b"NO_MEDIA_ID" in resp.body


@pytest.mark.parametrize("model", MODELS)
def test_guard_treats_a_blank_imdb_id_as_absent(model):
    """A whitespace-only id would tag nothing — it must not satisfy the guard."""
    req = model(kind="movie", title="X", imdb_id="   ")
    assert _require_any_id(req) is not None


def test_filenames_are_correct_without_a_tmdb_id():
    assert (
        build_poster_filename(
            kind="show",
            title="Obscure Show",
            year=2024,
            tmdb_id=None,
            tvdb_id=479037,
            imdb_id=None,
            season_number=None,
            ext=".png",
            asset_suffix=" - logo",
        )
        == "Obscure Show (2024) {tvdb-479037} - logo.png"
    )


def test_generate_requires_tmdb_id_or_a_supplied_backdrop():
    """GenerateRequest auto-sources art from TMDB (list_images) only when NO
    backdrop is supplied, so tmdb_id is required UNLESS a backdrop is handed over.
    (The endpoint's _require_any_id separately demands some id for the filename.)"""
    from pydantic import ValidationError

    from backend.api.cl2k_maker import GenerateRequest

    with pytest.raises(ValidationError):
        GenerateRequest(kind="movie", title="X")  # no id, no backdrop
    with pytest.raises(ValidationError):
        GenerateRequest(kind="show", title="X", tvdb_id=479037)  # id but no art source


def test_generate_accepts_a_tvdb_only_title_when_a_backdrop_is_supplied():
    """A TVDB/IMDB-only title is legitimate once the user supplies the backdrop —
    tmdb_id is only needed to auto-source one."""
    from backend.api.cl2k_maker import GenerateRequest

    req = GenerateRequest(
        kind="show", title="Obscure Show", tvdb_id=479037, backdrop_path="/p.jpg"
    )
    assert req.tmdb_id is None and req.tvdb_id == 479037
    # backdrop_b64 counts as a supplied backdrop too.
    assert (
        GenerateRequest(
            kind="movie", title="X", imdb_id="tt1", backdrop_b64="Zm9v"
        ).tmdb_id
        is None
    )


def test_seasons_request_requires_tmdb_id_or_a_backdrop():
    """SeasonsRequest carries the show backdrop over for each season; auto-source +
    season-reuse key on tmdb_id, so it's required unless a backdrop is supplied."""
    from pydantic import ValidationError

    from backend.api.cl2k_maker import SeasonsRequest

    with pytest.raises(ValidationError):
        SeasonsRequest(title="X", seasons=[1], tvdb_id=5)
    req = SeasonsRequest(title="X", seasons=[1], tvdb_id=5, backdrop_path="/p.jpg")
    assert req.tmdb_id is None


def test_app_mounts_with_the_relaxed_models():
    """Guards against a schema that pydantic accepts but FastAPI can't build."""
    from backend.api.cl2k_maker import router

    app = FastAPI()
    app.include_router(router)
    # openapi() forces FastAPI to build every route's schema — the step that
    # would blow up on a model it can't serialise.
    paths = app.openapi()["paths"]
    assert "/api/cl2k-maker/square-generate" in paths


def _cl2k_logger():
    """A no-op logger accepted by the CL2K endpoint + module."""
    import types

    return types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


def _render_config():
    """Minimal config for generate_for_item (skip_existing off; save is stubbed)."""
    import types

    return types.SimpleNamespace(
        cl2k_maker=types.SimpleNamespace(skip_existing=False),
        tmdb=types.SimpleNamespace(),
        sync_gdrive=types.SimpleNamespace(),
    )


def test_generate_endpoint_no_tmdb_path_completes_without_a_lookup(monkeypatch):
    """Endpoint: tmdb_id=None + a supplied backdrop + a TVDB id renders with NO TMDB
    lookup — the title is given and the art supplied, so nothing is auto-sourced."""
    from fastapi import BackgroundTasks

    import backend.modules.cl2k_maker as maker
    from backend.api import cl2k_maker as api

    monkeypatch.setattr(
        maker, "TMDBClient", lambda *a, **k: pytest.fail("TMDB used on the no-TMDB path")
    )
    seen = {}
    monkeypatch.setattr(
        maker,
        "_resolve_and_render",
        lambda *a, **kw: seen.update(kw)
        or (b"poster", {"backdrop_path": "/p.jpg", "logo_source": "tmdb"}),
    )
    monkeypatch.setattr(
        maker, "_persist_poster", lambda *a, **kw: {"status": "generated", "file": "x.png"}
    )
    monkeypatch.setattr(api, "load_config", _render_config)

    req = api.GenerateRequest(
        kind="show", title="Obscure Show", tvdb_id=479037, backdrop_b64="Zm9v"
    )
    resp = api.generate(req, BackgroundTasks(), db=object(), logger=_cl2k_logger())

    assert resp.status_code == 200
    assert seen["tmdb_id"] is None
    assert seen["tvdb_id"] == 479037
    assert seen["backdrop_bytes"] == b"foo"  # supplied backdrop forwarded, not auto-sourced


def test_generate_endpoint_blank_title_resolved_via_tmdb_id(monkeypatch):
    """Endpoint: a blank title with a tmdb_id resolves the canonical title from TMDB
    (by id) before naming/render, not saved as a bare id-tag filename."""
    from fastapi import BackgroundTasks

    import backend.modules.cl2k_maker as maker
    from backend.api import cl2k_maker as api

    class _FakeTMDB:
        def __init__(self, *a, **k):
            pass

        def find_tmdb_id(self, *a, **k):
            return None

        def get_details(self, tmdb_id, mt):
            return {"title": "Resolved Name", "year": 2020}

    monkeypatch.setattr(maker, "TMDBClient", _FakeTMDB)
    seen = {}
    monkeypatch.setattr(
        maker,
        "_resolve_and_render",
        lambda *a, **kw: seen.update(kw)
        or (b"poster", {"backdrop_path": None, "logo_source": "tmdb"}),
    )
    monkeypatch.setattr(
        maker, "_persist_poster", lambda *a, **kw: {"status": "generated", "file": "x.png"}
    )
    monkeypatch.setattr(api, "load_config", _render_config)

    req = api.GenerateRequest(kind="movie", title="", tmdb_id=603)
    resp = api.generate(req, BackgroundTasks(), db=object(), logger=_cl2k_logger())

    assert resp.status_code == 200
    assert seen["title"] == "Resolved Name"  # backfilled from TMDB by id


# --- Art-picker endpoints: TMDB art is keyed by tmdb_id, but the caller need
# --- not supply one — a tvdb/imdb id is resolved first.


class _ResolvingTMDB:
    """TMDBClient stub: knows one tvdb->tmdb mapping, nothing else."""

    def __init__(self, *a, **k):
        pass

    def find_tmdb_id(self, external_id, source, media_type):
        """Resolve only the one id the tests use."""
        return 1399 if (external_id, source) == ("479037", "tvdb_id") else None


def _picker_api(monkeypatch):
    """The cl2k_maker api module with TMDB + config stubbed for picker calls."""
    from backend.api import cl2k_maker as api

    monkeypatch.setattr(api, "TMDBClient", _ResolvingTMDB)
    monkeypatch.setattr(api, "load_config", _render_config)
    return api


def _body(resp):
    import json

    return json.loads(resp.body)["data"]


def test_images_resolves_a_tvdb_only_title(monkeypatch):
    """A show with no tmdb_id still gets its TMDB art, via the tvdb id."""
    api = _picker_api(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        api.tmdb_art,
        "list_images",
        lambda tmdb, tid, mt: seen.update(tmdb_id=tid) or {"logos": [], "backdrops": []},
    )

    resp = api.images(
        tmdb_id=None,
        tvdb_id=479037,
        imdb_id=None,
        media_type="show",
        db=object(),
        logger=_cl2k_logger(),
    )

    assert resp.status_code == 200
    assert seen["tmdb_id"] == 1399  # resolved, not demanded


def test_images_with_no_ids_is_empty_not_an_error(monkeypatch):
    """A title carrying no id at all degrades to empty art, never a 422."""
    api = _picker_api(monkeypatch)
    monkeypatch.setattr(
        api.tmdb_art,
        "list_images",
        lambda *a, **k: pytest.fail("TMDB must not be queried without an id"),
    )

    resp = api.images(
        tmdb_id=None,
        tvdb_id=None,
        imdb_id=None,
        media_type="movie",
        db=object(),
        logger=_cl2k_logger(),
    )

    assert resp.status_code == 200
    assert _body(resp) == {"logos": [], "backdrops": [], "posters": []}


def test_season_images_resolves_a_tvdb_only_show(monkeypatch):
    """Season posters follow the same rule — tvdb id in, TMDB season art out."""
    api = _picker_api(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        api.tmdb_art,
        "list_season_images",
        lambda tmdb, tid, sn: seen.update(tmdb_id=tid, season=sn) or {"posters": []},
    )

    resp = api.season_images(
        tmdb_id=None,
        tvdb_id=479037,
        imdb_id=None,
        season_number=2,
        db=object(),
        logger=_cl2k_logger(),
    )

    assert resp.status_code == 200
    assert (seen["tmdb_id"], seen["season"]) == (1399, 2)


def test_external_ids_resolves_a_tvdb_only_title(monkeypatch):
    """The id backfill works from a tvdb id, so imdb_id can still be filled in."""
    api = _picker_api(monkeypatch)
    monkeypatch.setattr(
        api.tmdb_art,
        "external_ids",
        lambda tmdb, tid, mt: {"tvdb_id": 479037, "imdb_id": "tt0903747"},
    )

    resp = api.external_ids(
        tmdb_id=None,
        tvdb_id=479037,
        imdb_id=None,
        media_type="show",
        db=object(),
        logger=_cl2k_logger(),
    )

    assert resp.status_code == 200
    assert _body(resp)["imdb_id"] == "tt0903747"
