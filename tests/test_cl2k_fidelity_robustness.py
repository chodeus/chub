"""Tests for CL2K render fidelity + endpoint robustness (D3+D4).

Fidelity — what the user approved in the preview is what gets written:
* /psd-export forwards the uploaded backdrop/logo and the brush masks, instead of
  rebuilding the document from TMDB art;
* the .psd LOGO layer is the renderer's OWN processed logo, so the two-tone
  post-passes can no longer be missing from it alone;
* the save-as-is pipeline encodes the JPEG once instead of round-tripping it
  between the label/logo and border steps.

Robustness — a bad request must not read as a server fault or a green toast:
* the saving routes answer bad input with the same clean 4xx the previews do;
* a Drive upload is deferred whenever the caller can defer it, /retext included;
* a season poll can't disagree with itself, and an all-failed batch is not "done";
* an SVG can't slip past the sniff into ImageMagick's delegate;
* a blank title can't 500 the wordmark fallback;
* a brush mask that fails late is logged, not silently dropped.
"""

import base64
import io
import json
import logging
import types

import pytest

pytest.importorskip("wand.image")  # cl2k extra (the API pulls in the renderer)

import numpy as np  # noqa: E402
from fastapi import BackgroundTasks  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from wand.color import Color  # noqa: E402
from wand.drawing import Drawing  # noqa: E402
from wand.image import Image  # noqa: E402

import backend.api.cl2k_maker as api  # noqa: E402
import backend.modules.cl2k_maker as maker  # noqa: E402
from backend.util.cl2k import geometry as geo, renderer  # noqa: E402

_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="10"></svg>'
# Stands in for what a real exception leaks: a path, a credential, a provider reply.
_SECRET = "/srv/secret-path: token=hunter2 (rclone said no)"


# fixtures


def _logger():
    """Silent logger for calls whose log output no assertion reads."""
    noop = lambda *a, **k: None  # noqa: E731
    return types.SimpleNamespace(debug=noop, info=noop, warning=noop, error=noop)


def _recording_logger():
    """A logger that keeps every warning/error line, for the empty-log findings."""
    lines = []
    noop = lambda *a, **k: None  # noqa: E731
    return lines, types.SimpleNamespace(
        debug=noop,
        info=noop,
        warning=lambda m, *a, **k: lines.append(str(m)),
        error=lambda m, *a, **k: lines.append(str(m)),
    )


def _png(w, h, draw_fn):
    """PNG bytes of a transparent canvas painted by ``draw_fn``."""
    with Image(width=w, height=h, background=Color("transparent")) as img:
        with Drawing() as d:
            draw_fn(d)
            d(img)
        img.format = "png"
        return img.make_blob()


def _two_colour_logo():
    """Two saturated fills meeting with NO outline between them.

    The whiten key turns both white, so only the colour-edge post-pass puts a
    black separator back — which is what makes this fixture able to tell the
    finished two-tone apart from a bare whiten.
    """

    def draw(d):
        """Paint the two abutting fills."""
        d.fill_color = Color("#e01b24")
        d.rectangle(left=0, top=0, width=499, height=299)
        d.fill_color = Color("#1c71d8")
        d.rectangle(left=500, top=0, width=999, height=299)

    return _png(1000, 300, draw)


def _mask_png(w=400, h=120):
    """A fully-painted brush mask (white = act on every pixel)."""
    with Image(width=w, height=h, background=Color("white")) as mask:
        mask.format = "png"
        return mask.make_blob()


def _backdrop(w=1920, h=1080):
    """Flat-colour JPEG standing in for a TMDB backdrop."""
    with Image(width=w, height=h, background=Color("#27408b")) as bg:
        bg.format = "jpeg"
        return bg.make_blob()


def _poster_jpeg():
    """A finished poster already on the locked 1000x1500 canvas."""
    with Image(width=geo.CANVAS_W, height=geo.CANVAS_H, background=Color("#123456")) as p:
        p.format = "jpeg"
        return p.make_blob()


def _b64(raw: bytes) -> str:
    """Base64 the bytes the way the frontend hands them over."""
    return base64.b64encode(raw).decode()


def _body(resp):
    """The decoded JSON envelope of a JSONResponse."""
    return json.loads(bytes(resp.body))


def _rgba(im) -> np.ndarray:
    """Float RGBA array of a PIL image, for pixel comparisons."""
    return np.asarray(im.convert("RGBA")).astype(np.float32)


def _min_opaque_luma(im) -> float:
    """Darkest luma among the opaque pixels — 0 means real black ink."""
    arr = _rgba(im)
    return float(arr[..., :3].mean(axis=2)[arr[..., 3] > 200].min())


# 1. /psd-export renders from the SAME inputs as the preview


def test_psd_export_forwards_the_uploaded_and_brushed_art(monkeypatch):
    """It forwarded only the *paths*, so the .psd came out of TMDB art while the
    preview beside it showed the user's upload and brush strokes."""
    seen = {}
    monkeypatch.setattr(api, "load_config", object)
    monkeypatch.setattr(
        api, "psd_for_item", lambda **kw: (seen.update(kw), b"psd-bytes")[1]
    )
    art, logo, flip, erase = b"ART", b"LOGO", b"FLIP", b"ERASE"
    req = api.GenerateRequest(
        kind="movie",
        title="T",
        tmdb_id=7,
        backdrop_b64=_b64(art),
        logo_b64=_b64(logo),
        logo_flip_b64=_b64(flip),
        logo_erase_b64=_b64(erase),
    )

    api.psd_export(req, db=object(), logger=_logger())

    assert seen["backdrop_bytes"] == art
    assert seen["custom_logo_bytes"] == logo
    assert seen["logo_flip_bytes"] == flip
    assert seen["logo_erase_bytes"] == erase


def test_psd_for_item_uses_the_uploaded_art_without_re_resolving(monkeypatch):
    """Uploaded bytes mean "don't auto-resolve this" — the same rule the render
    path follows. Re-resolving would put a different picture in the .psd."""
    monkeypatch.setattr(maker, "TMDBClient", lambda *a, **k: object())
    needs = {}
    monkeypatch.setattr(
        maker,
        "_resolve_default_art",
        lambda *a, **kw: (needs.update(kw), (None, None))[1],
    )
    monkeypatch.setattr(
        maker.image_fetch,
        "download",
        lambda *a, **k: pytest.fail("downloaded art despite an upload"),
    )
    monkeypatch.setattr(maker.renderer, "frame_backdrop", lambda **kw: kw["backdrop_bytes"])
    seen = {}
    monkeypatch.setattr(
        "backend.util.cl2k.psd_export.export_psd",
        lambda **kw: (seen.update(kw), b"psd")[1],
    )

    out = maker.psd_for_item(
        db=object(),
        full_config=types.SimpleNamespace(
            cl2k_maker=types.SimpleNamespace(language="en", whiten_logo=True),
            tmdb=None,
        ),
        logger=_logger(),
        kind="movie",
        title="T",
        tmdb_id=7,
        backdrop_bytes=b"ART",
        custom_logo_bytes=b"LOGO",
        logo_flip_bytes=b"FLIP",
        logo_erase_bytes=b"ERASE",
    )

    assert out == b"psd"
    # Both auto-picks switched off, so a TMDB backdrop/logo can't replace the upload.
    assert needs == {"need_backdrop": False, "need_logo": False}
    assert seen["backdrop_bytes"] == b"ART"
    assert seen["logo_bytes"] == b"LOGO"
    assert (seen["logo_flip_bytes"], seen["logo_erase_bytes"]) == (b"FLIP", b"ERASE")


# 2. the .psd LOGO layer IS the render's processed logo


def test_psd_logo_layer_is_the_renderers_own_processed_logo():
    """A Pillow re-implementation of the whiten chain drifted from the render —
    it stopped after the key, with no colour-edge or dark-body post-pass."""
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage

    from backend.util.cl2k.psd_export import export_psd

    src = _two_colour_logo()
    blob = export_psd(
        backdrop_bytes=renderer.frame_backdrop(backdrop_bytes=_backdrop()),
        kind="movie",
        logo_bytes=src,
    )
    psd = PSDImage.open(io.BytesIO(blob))
    group = next(la for la in psd if la.name == "LOGO")
    layer = group.composite(viewport=(0, 0, psd.width, psd.height)).convert("RGBA")
    layer = layer.crop(layer.getbbox())

    processed, pw, ph = renderer.process_logo(src, whiten=True)
    tw, th = geo.auto_logo_size(pw, ph, geo.MAIN_LOGO_BOTTOM)
    ref = PILImage.open(io.BytesIO(processed)).convert("RGBA")
    ref = ref.resize((tw, th), PILImage.Resampling.LANCZOS)
    ref = ref.crop(ref.getbbox())

    assert layer.size == ref.size
    assert np.abs(_rgba(layer) - _rgba(ref)).max() == 0
    # Non-vacuity: a bare whiten leaves this fixture a pure-white blob, so a dark
    # pixel is proof the post-passes ran rather than the assert being trivial.
    assert _min_opaque_luma(layer) < 32


def test_psd_logo_layer_applies_the_brush_masks():
    """The erase brush must reach the .psd too, or the LOGO layer keeps bits the
    user painted away in the preview."""
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage

    from backend.util.cl2k.psd_export import export_psd

    framed = renderer.frame_backdrop(backdrop_bytes=_backdrop())
    src = _two_colour_logo()

    def _opaque(erase):
        """Opaque pixel count of the LOGO layer for one erase mask."""
        blob = export_psd(
            backdrop_bytes=framed, kind="movie", logo_bytes=src, logo_erase_bytes=erase
        )
        psd = PSDImage.open(io.BytesIO(blob))
        group = next(la for la in psd if la.name == "LOGO")
        layer = group.composite(viewport=(0, 0, psd.width, psd.height)).convert("RGBA")
        return int((_rgba(layer)[..., 3] > 200).sum())

    assert _opaque(_mask_png()) < _opaque(None) * 0.75


# 3. the save-as-is pipeline encodes once


def test_the_as_is_pipeline_encodes_the_jpeg_once(monkeypatch):
    """Label then border were two calls, so the poster was decoded and re-encoded
    between them — a lossy round-trip for nothing."""
    encodes = []
    real = renderer._encode_jpeg
    monkeypatch.setattr(
        renderer, "_encode_jpeg", lambda base: (encodes.append(1), real(base))[1]
    )

    out = maker.retext_poster(
        db=object(),
        full_config=types.SimpleNamespace(cl2k_maker=types.SimpleNamespace()),
        logger=_logger(),
        image_bytes=_poster_jpeg(),
        label_text="SEASON TWO",
        add_border=True,
        save=False,
    )

    assert out[:2] == b"\xff\xd8"  # still a JPEG
    assert len(encodes) == 1


def test_folding_the_border_in_matches_applying_it_separately():
    """Same picture, one encode fewer — the fold must not move any pixels."""
    poster = _poster_jpeg()
    logo = _two_colour_logo()
    folded = renderer.overlay_logo(poster, logo, kind="movie", add_border=True)
    staged = renderer.apply_border(renderer.overlay_logo(poster, logo, kind="movie"))

    a, b = _rgba(PILImage.open(io.BytesIO(folded))), _rgba(PILImage.open(io.BytesIO(staged)))
    assert a.shape == b.shape
    # Only the JPEG round-trip the fold removes separates them.
    assert np.abs(a - b).mean() < 1.0


# 4. the saving routes answer bad input like the previews do


def _boom(*a, **kw):
    """Stand-in for a call that fails on bad input."""
    raise RuntimeError("image host is not allowed")


def _boom_secret(*a, **kw):
    """Fails with text that must never reach a response body."""
    raise RuntimeError(_SECRET)


_SAVE_ROUTES = ("generate", "square_generate", "background_generate", "logo_asset_generate")


@pytest.mark.parametrize("route", _SAVE_ROUTES)
def test_a_saving_route_answers_bad_input_with_a_clean_400(route, monkeypatch):
    """They 500'd with an empty CL2K log for bodies the previews already 400'd."""
    monkeypatch.setattr(api, "load_config", object)
    for name in (
        "generate_for_item",
        "generate_square_art",
        "generate_background_art",
        "generate_logo_asset",
    ):
        monkeypatch.setattr(api, name, _boom)
    lines, logger = _recording_logger()
    req_cls = {
        "generate": api.GenerateRequest,
        "square_generate": api.SquareArtRequest,
        "background_generate": api.BackgroundArtRequest,
        "logo_asset_generate": api.LogoAssetRequest,
    }[route]
    req = req_cls(kind="movie", title="T", tmdb_id=7)

    resp = getattr(api, route)(
        req, background_tasks=BackgroundTasks(), db=object(), logger=logger
    )

    assert resp.status_code == 400
    body = _body(resp)
    assert body["error_code"] == "CL2K_GENERATE"
    # Readable, but the exception text stays server-side (py/stack-trace-exposure).
    assert "image host is not allowed" not in body["message"]
    assert "CL2K Maker log" in body["message"]
    assert any("image host is not allowed" in line for line in lines), "and it must be logged"


def test_psd_export_answers_bad_input_with_a_clean_400(monkeypatch):
    """The .psd export was the last saving route with no guard at all."""
    monkeypatch.setattr(api, "load_config", object)
    monkeypatch.setattr(api, "psd_for_item", _boom)
    resp = api.psd_export(
        api.GenerateRequest(kind="movie", title="T", tmdb_id=7),
        db=object(),
        logger=_logger(),
    )
    assert resp.status_code == 400
    assert _body(resp)["error_code"] == "PSD_EXPORT"


@pytest.mark.parametrize("route", ["square_preview", "background_preview"])
def test_an_art_preview_answers_a_disallowed_host_with_a_clean_400(route, monkeypatch):
    """Same class as the saving routes: the fetch raises before any render."""
    monkeypatch.setattr(api, "download_image", _boom)
    req_cls = {
        "square_preview": api.SquareArtRequest,
        "background_preview": api.BackgroundArtRequest,
    }[route]
    resp = getattr(api, route)(
        req_cls(kind="movie", title="T", tmdb_id=7, backdrop_path="http://evil/x.jpg"),
        db=object(),
        logger=_logger(),
    )
    assert resp.status_code == 400
    assert _body(resp)["error_code"] == "IMAGE_FETCH"


_ART = "http://x/y.jpg"
_FETCH_ROUTES = [
    # retext needs an id (a save must be matchable) and its own BackgroundTasks.
    pytest.param("retext", api.RetextRequest, {"tmdb_id": 7}, True, id="retext"),
    pytest.param("detect_text", api.DetectTextRequest, {}, False, id="detect-text"),
    pytest.param("tighten_mask", api.TightenMaskRequest, {}, False, id="tighten-mask"),
]


@pytest.mark.parametrize("route, req_cls, fields, needs_tasks", _FETCH_ROUTES)
def test_no_route_puts_exception_text_in_the_response(
    route, req_cls, fields, needs_tasks, monkeypatch
):
    """py/stack-trace-exposure: exception text names paths, hosts and tokens, so
    it belongs in the CL2K log and never in the body the browser reads."""
    monkeypatch.setattr(api, "download_image", _boom_secret)
    lines, logger = _recording_logger()
    extra = {"background_tasks": BackgroundTasks()} if needs_tasks else {}

    resp = getattr(api, route)(
        req_cls(image_path=_ART, **fields), db=object(), logger=logger, **extra
    )

    assert resp.status_code == 400
    assert _SECRET not in _body(resp)["message"]
    assert any(_SECRET in line for line in lines), "the reason must still be logged"


def test_a_failing_season_worker_keeps_its_reason_out_of_the_poll(monkeypatch):
    """/seasons-status serialises job["error"] and each result's reason straight to
    the browser, so a raw str(exc) there is the same leak by another route."""
    monkeypatch.setattr(api, "load_config", object)
    monkeypatch.setattr(api, "retext_poster", _boom_secret)
    _lines, logger = _recording_logger()
    jid = api._new_season_job(1, "Show")
    api._run_retext_seasons_job(
        jid, object(), logger, b"", api.RetextSeasonsRequest(seasons=[1], tmdb_id=1)
    )

    data = _body(api.seasons_status(jid))["data"]
    assert data["failed"] == 1
    assert _SECRET not in json.dumps(data)


def test_a_real_http_status_is_not_downgraded_to_400(monkeypatch):
    """An upstream 401/403 must keep its status — only bad input becomes a 400."""
    from fastapi import HTTPException

    monkeypatch.setattr(api, "load_config", object)

    def _unauthorized(**kw):
        """Fails the way an upstream 401 does."""
        raise HTTPException(status_code=401, detail="nope")

    monkeypatch.setattr(api, "generate_for_item", _unauthorized)
    with pytest.raises(HTTPException) as exc:
        api.generate(
            api.GenerateRequest(kind="movie", title="T", tmdb_id=7),
            background_tasks=BackgroundTasks(),
            db=object(),
            logger=_logger(),
        )
    assert exc.value.status_code == 401


# 5. rclone never runs in the request thread when it can be deferred


def test_retext_can_defer_its_upload():
    """Every /retext save uploaded inline; the wiring must reach all three."""
    import inspect

    assert "background_tasks" in inspect.signature(api.retext).parameters
    for fn in (maker.retext_poster, maker.save_finished_poster):
        assert "defer_upload" in inspect.signature(fn).parameters, f"{fn.__name__}"


def _drive_only(monkeypatch, uploaded):
    """Route a Drive folder and NO local folder; returns (config, notifications)."""
    notes = []

    class FakeNotifier:
        """Captures what a deferred failure would have told the user."""

        def __init__(self, *a, **k):
            """Accept whatever the real NotificationManager takes."""
            pass

        def send_notification(self, output, event="success"):
            """Record the event instead of sending it."""
            notes.append((event, output))
            return {}

    monkeypatch.setattr(
        "backend.util.notification.NotificationManager", FakeNotifier, raising=False
    )
    monkeypatch.setattr(maker, "_drive_targets", lambda cfg, image_type: ["folder-A"])
    monkeypatch.setattr(maker, "_local_targets", lambda cfg, image_type: [])
    monkeypatch.setattr(
        "backend.util.cl2k.gdrive_upload.upload_file",
        lambda path, folder, cfg, logger: uploaded.append(folder),
        raising=False,
    )
    monkeypatch.setattr(
        maker,
        "cl2k_generated_for",
        lambda db: types.SimpleNamespace(
            mark_uploaded=lambda *a, **k: None, record=lambda *a, **k: None
        ),
    )
    cfg = types.SimpleNamespace(
        local_folders=[], gdrive_uploads=[], style="CL2K", priority=0
    )
    full = types.SimpleNamespace(cl2k_maker=cfg, sync_gdrive=object())
    monkeypatch.setattr("backend.util.config.load_config", lambda: full, raising=False)
    return full, notes


def _persist_drive_only(full, queued, logger):
    """Run the Drive-only save under test (no local folder claims the type)."""
    return maker._persist_poster(
        db=types.SimpleNamespace(poster=types.SimpleNamespace(bulk_upsert=lambda r: None)),
        cfg=full.cl2k_maker,
        logger=logger,
        sync_cfg=object(),
        blob=b"jpeg",
        kind="movie",
        title="T",
        year=2020,
        tmdb_id=1,
        tvdb_id=None,
        imdb_id=None,
        season_number=None,
        backdrop_path=None,
        logo_source="",
        defer_upload=queued.append,
        full_config=full,
    )


def test_a_drive_only_save_defers_instead_of_uploading_inline(monkeypatch):
    """rclone ran in the request thread whenever no local folder was configured,
    so a slow link 504'd a save that in fact succeeded."""
    uploaded, queued = [], []
    full, notes = _drive_only(monkeypatch, uploaded)

    result = _persist_drive_only(full, queued, _logger())

    assert not uploaded, "the upload must not run before the response"
    assert queued, "it must be queued instead"
    # Without a local copy this used to fall through to "nothing landed anywhere".
    assert result["status"] == "generated"
    assert result["upload_pending"] is True

    queued[0]()  # BackgroundTasks would call this after the response
    assert uploaded == ["folder-A"]
    assert not notes, "a clean deferred upload must stay quiet"


def test_a_deferred_run_that_crashes_before_the_upload_still_reports(monkeypatch):
    """Staging runs BEFORE the per-folder guard, so a mkdtemp/write failure escaped
    into the background task — the caller kept "uploading to Drive" for good."""
    uploaded, queued, errors = [], [], []
    full, notes = _drive_only(monkeypatch, uploaded)

    def _no_tmpdir(*a, **k):
        """Break staging the way a full disk would."""
        raise OSError("no space left on device")

    # Module-scoped swap, so no other test inherits a broken tempfile.
    monkeypatch.setattr(maker, "tempfile", types.SimpleNamespace(mkdtemp=_no_tmpdir))
    logger = _logger()
    logger.error = errors.append

    result = _persist_drive_only(full, queued, logger)
    assert result["upload_pending"] is True
    assert not notes, "nothing should be reported before the deferred task runs"

    queued[0]()  # BackgroundTasks runs it after the response — must not raise

    assert not uploaded, "staging failed, so nothing was uploaded"
    assert any(e == "failure" for e, _ in notes), "the crash has to reach the user"
    assert any("FAILED" in m for m in errors), "and must log at error level"


# 6+7. the season poll can't disagree with itself, and can't fake success


def _job(results, status="done", total=None):
    """Register a season job already carrying ``results``."""
    jid = api._new_season_job(total if total is not None else len(results), "Show")
    with api._season_jobs_lock:
        api._season_jobs[jid]["results"] = list(results)
        api._season_jobs[jid]["done"] = len(results)
        api._season_jobs[jid]["status"] = status
    return jid


def test_a_snapshot_does_not_alias_the_workers_results_list():
    """dict(job) copied the mapping but not the list inside it, so a poll could
    serialise more results than the `done` it had just read."""
    jid = _job([], status="running", total=3)
    snap = api._season_job_snapshot(jid)
    with api._season_jobs_lock:
        api._season_jobs[jid]["results"].append({"season": 1, "status": "generated"})

    assert snap["results"] == []
    assert snap["done"] == len(snap["results"])


def test_an_all_failed_batch_is_not_reported_as_done():
    """status "done" + no failure count showed a green "0/3 generated" toast."""
    jid = _job([{"season": n, "status": "error", "reason": "x"} for n in (1, 2, 3)])
    data = _body(api.seasons_status(jid))["data"]

    assert (data["generated"], data["failed"]) == (0, 3)
    assert data["status"] == "error"
    assert data["outcome"] == "error"
    assert "3" in (data["error"] or "")


def test_a_partly_failed_batch_reports_its_failures():
    """Some failed, some landed: additive fields carry it, status stays done."""
    jid = _job(
        [
            {"season": 1, "status": "generated"},
            {"season": 2, "status": "error", "reason": "x"},
            {"season": 3, "status": "skipped", "reason": "already generated"},
        ]
    )
    data = _body(api.seasons_status(jid))["data"]

    assert (data["generated"], data["failed"]) == (1, 1)  # a skip is not a failure
    assert data["outcome"] == "partial"
    # The existing poller only terminates on done/error, so the lifecycle field
    # must not grow a third terminal value until the page learns it.
    assert data["status"] == "done"


def test_a_clean_batch_still_reads_as_success():
    """The escalation must not fire on a batch that generated everything."""
    jid = _job([{"season": n, "status": "generated"} for n in (1, 2)])
    data = _body(api.seasons_status(jid))["data"]
    assert (data["status"], data["outcome"], data["failed"]) == ("done", "ok", 0)


# 8. no SVG reaches ImageMagick's delegate


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param(b"", id="bare"),
        pytest.param(b"\xef\xbb\xbf", id="utf8-bom"),
        pytest.param(b"\n  \t", id="leading-space"),
        pytest.param(b"<?xml version='1.0' encoding='UTF-8'?>\n", id="xml-decl"),
        pytest.param(b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd">\n', id="doctype"),
        pytest.param(b"<!-- exported by a design tool -->\n", id="comment"),
        pytest.param(b"\xef\xbb\xbf<?xml version='1.0'?>\n<!-- c -->\n", id="bom+decl+comment"),
    ],
)
def test_a_prefixed_svg_is_still_recognised(prefix):
    """Anything before the root tag used to defeat the sniff, dropping the file
    through to ImageMagick's librsvg delegate — which cairosvg's unsafe=False
    hardening is there to keep it away from."""
    assert renderer._is_svg(prefix + _SVG)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(_png(4, 4, lambda d: None), id="png"),
        pytest.param(_backdrop(8, 8), id="jpeg"),
        pytest.param(b"GIF89a" + b"\x00" * 16 + b"<svg", id="gif-with-svg-in-metadata"),
        pytest.param(b"", id="empty"),
    ],
)
def test_a_raster_is_not_mistaken_for_an_svg(raw):
    """The looser scan must not send real image bytes to the rasterizer."""
    assert not renderer._is_svg(raw)


def test_a_prefixed_svg_is_rasterized_rather_than_handed_to_wand(monkeypatch):
    """Recognising it is only half the fix — it must also take the safe path."""
    seen = []
    monkeypatch.setattr(
        renderer,
        "_rasterize_svg_logo",
        lambda b, target_width=2000: (seen.append(b), _png(4, 4, lambda d: None))[1],
    )
    renderer._read_logo_image(b"\xef\xbb\xbf" + _SVG).close()
    assert seen and seen[0].endswith(_SVG)


# 9. the wordmark fallback cannot 500


def test_a_blank_title_cannot_500_the_logo_fallback():
    """A whitespace title is truthy but typesets to b"", which Wand cannot decode.
    Raised inside the except handler, that turned a bad logo into a 500."""
    blob = renderer.render_cl2k(
        backdrop_bytes=_backdrop(),
        kind="movie",
        logo_bytes=b"not an image at all",
        title="   ",
    )
    assert blob[:2] == b"\xff\xd8"


def test_a_real_title_still_falls_back_to_the_wordmark():
    """The hoist must not cost the fallback it exists to protect."""
    plain = renderer.render_cl2k(backdrop_bytes=_backdrop(), kind="movie", title="")
    fell_back = renderer.render_cl2k(
        backdrop_bytes=_backdrop(),
        kind="movie",
        logo_bytes=b"not an image at all",
        title="Some Title",
    )
    assert fell_back != plain, "nothing was drawn in the logo area"


def test_an_unplaceable_logo_with_no_title_still_renders():
    """No logo and no title is a logo-less poster, not a failure."""
    blob = renderer.render_cl2k(
        backdrop_bytes=_backdrop(), kind="movie", logo_bytes=b"nope", title=""
    )
    assert blob[:2] == b"\xff\xd8"


# 10. a dropped brush edit is never silent


@pytest.mark.parametrize(
    "fn, verb", [(renderer._flip_regions, "flip"), (renderer._erase_regions, "erase")]
)
def test_a_late_brush_failure_is_logged_not_swallowed(fn, verb, monkeypatch, caplog):
    """`except: pass` around the WHOLE body meant a mask that decoded but failed
    later dropped the user's edits, and the poster was saved without them."""
    monkeypatch.setattr(renderer, "_COPY_ALPHA", "not_a_composite_operator")
    with Image(blob=_two_colour_logo()) as logo:
        with caplog.at_level(logging.WARNING, logger=renderer.__name__):
            fn(logo, _mask_png())  # fail open: must not raise
        assert logo.width > 0  # and the logo survives for the render

    assert any(f"logo {verb} failed" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "fn, verb", [(renderer._flip_regions, "flip"), (renderer._erase_regions, "erase")]
)
def test_an_undecodable_brush_mask_stays_tolerant(fn, verb, caplog):
    """The decode guard keeps its no-op behaviour, but says so now."""
    with Image(blob=_two_colour_logo()) as logo:
        with caplog.at_level(logging.WARNING, logger=renderer.__name__):
            fn(logo, b"not a png")
    assert any(f"logo {verb} mask is undecodable" in r.getMessage() for r in caplog.records)
