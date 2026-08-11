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
