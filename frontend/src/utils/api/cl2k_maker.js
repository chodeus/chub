/** CL2K Poster Maker API. Its binary endpoints go through postBlob, bypassing apiCore,
 *  which would corrupt raw bytes by reading the body as JSON/text. */

import { apiCore } from './core.js';

const ENCODE = encodeURIComponent;
const TOKEN_STORAGE_KEY = 'chub-auth-token';

// Client timeout for AI-bound calls (OpenAI text removal, PSD flatten). Must be
// LONGER than the backend ai_timeout (default 300s) so the backend's own error
// surfaces instead of a silent client-side abort.
const AI_TIMEOUT_MS = 360000;

const qs = params => {
    const sp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
    });
    return sp.toString();
};

/** POST JSON, returning the raw body as a Blob. `signal` aborts a stale render when
 *  the sliders move again, instead of piling requests on the backend. */
const postBlob = async (path, body, { signal } = {}) => {
    // AI-bound blobs get the same ceiling as the JSON calls; a caller signal wins.
    signal = signal ?? AbortSignal.timeout(AI_TIMEOUT_MS);
    const headers = { 'Content-Type': 'application/json' };
    try {
        const token = localStorage.getItem(TOKEN_STORAGE_KEY);
        if (token) headers['Authorization'] = `Bearer ${token}`;
    } catch {
        /* localStorage unavailable — skip */
    }
    const resp = await fetch(`/api${path}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal,
    });
    if (!resp.ok) {
        // Error bodies are JSON ({message, error_code}); surface the message.
        let message = `HTTP ${resp.status}`;
        try {
            const data = await resp.json();
            message = data?.message || message;
        } catch {
            /* non-JSON error body */
        }
        throw new Error(message);
    }
    return resp.blob();
};

export const cl2kMakerAPI = {
    /** TMDB title search. type = movie | show | collection. */
    search: (q, type = 'movie') =>
        apiCore.get(`/cl2k-maker/search?${qs({ q, type })}`, { useCache: false }),

    /** Resolve an external id (tvdb/imdb) to a tmdb id. */
    resolve: (externalId, source, type = 'movie') =>
        apiCore.get(`/cl2k-maker/resolve?${qs({ external_id: externalId, source, type })}`, {
            useCache: false,
        }),

    /** All TMDB logos + backdrops for the art picker. Resolves via TMDB →
     *  TVDB → IMDB, so a TVDB/IMDB-only title still gets its TMDB art. */
    images: (tmdbId, type = 'movie', { tvdbId, imdbId } = {}) =>
        apiCore.get(
            `/cl2k-maker/images?${qs({ tmdb_id: tmdbId, type, tvdb_id: tvdbId, imdb_id: imdbId })}`,
            {
                useCache: true,
                cacheTTL: 5 * 60 * 1000,
            }
        ),

    /** fanart.tv logo + background for the art picker. */
    fanartImages: ({ tmdbId, type = 'movie', tvdbId, imdbId, seasonNumber } = {}) =>
        apiCore.get(
            `/cl2k-maker/fanart-images?${qs({
                tmdb_id: tmdbId,
                type,
                tvdb_id: tvdbId,
                imdb_id: imdbId,
                season_number: seasonNumber,
            })}`,
            { useCache: true, cacheTTL: 5 * 60 * 1000 }
        ),

    /** Plex artwork (clearLogos + backgrounds + posters) for the art picker —
     *  read-only; resolves the item to a ratingKey via the synced plex cache.
     *  Not cached: URLs carry a token that can rotate. */
    plexImages: ({ tmdbId, type = 'movie', tvdbId, imdbId } = {}) =>
        apiCore.get(
            `/cl2k-maker/plex-images?${qs({
                tmdb_id: tmdbId,
                type,
                tvdb_id: tvdbId,
                imdb_id: imdbId,
            })}`,
            { useCache: false }
        ),

    /** TMDB season-level posters (portrait 2:3) for the art picker. */
    seasonImages: (tmdbId, seasonNumber, { tvdbId, imdbId } = {}) =>
        apiCore.get(
            `/cl2k-maker/season-images?${qs({
                tmdb_id: tmdbId,
                season_number: seasonNumber,
                tvdb_id: tvdbId,
                imdb_id: imdbId,
            })}`,
            { useCache: true, cacheTTL: 5 * 60 * 1000 }
        ),

    /** Canonical TMDB title + year for an id (fills an id-only entry). Resolves
     *  via TMDB → TVDB → IMDB, so a TVDB/IMDB-only title still resolves. */
    details: (tmdbId, type = 'movie', { tvdbId, imdbId } = {}) =>
        apiCore.get(
            `/cl2k-maker/details?${qs({
                tmdb_id: tmdbId,
                tvdb_id: tvdbId,
                imdb_id: imdbId,
                type,
            })}`,
            { useCache: true, cacheTTL: 5 * 60 * 1000 }
        ),

    /** Trimmed + whitened logo (b64 PNG + natural size + the box_w/box_h the
     *  render would place it at) for the live overlay.
     *  `req` = { logo_path | logo_b64, kind }. */
    logoProcessed: req => apiCore.post('/cl2k-maker/logo-processed', req),

    /** Render a preview JPEG without saving. Returns a Blob. */
    preview: (req, opts) => postBlob('/cl2k-maker/preview', req, opts),

    /** Render + write + cache + record provenance. */
    generate: req => apiCore.post('/cl2k-maker/generate', req),

    /** Render square art (1:1) without saving. Returns a JPEG Blob. */
    squarePreview: (req, opts) => postBlob('/cl2k-maker/square-preview', req, opts),

    /** Render + file square art (`- squareart.jpg`). */
    squareGenerate: req => apiCore.post('/cl2k-maker/square-generate', req),

    /** Render background art (16:9) without saving. Returns a JPEG Blob. */
    backgroundPreview: (req, opts) => postBlob('/cl2k-maker/background-preview', req, opts),

    /** Render + file background art (`- background.jpg`, 1080p or 4K). */
    backgroundGenerate: req => apiCore.post('/cl2k-maker/background-generate', req),

    /** Processed logo asset (transparent PNG) without saving. Returns a PNG Blob.
     *  `req` = { logo_path | logo_b64, whiten }. */
    logoAssetPreview: (req, opts) => postBlob('/cl2k-maker/logo-asset-preview', req, opts),

    /** File a clear logo as a `- logo.png` asset (whiten toggles CL2K white). */
    logoAssetGenerate: req => apiCore.post('/cl2k-maker/logo-asset-generate', req),

    /** Extract a white title from a poster into a transparent logo PNG. Returns a
     *  Blob. `req` = { image_b64 | image_path, mask_b64, lo, hi }. */
    extractLogo: req => postBlob('/cl2k-maker/extract-logo', req),

    /** Recently generated posters (provenance). `opts` carries a caller signal. */
    generated: (limit = 200, opts) =>
        apiCore.get(`/cl2k-maker/generated?${qs({ limit })}`, { useCache: false, ...opts }),

    /** Export the poster as a layered .psd. Returns a Blob. */
    psdExport: req => postBlob('/cl2k-maker/psd-export', req),

    /** Start a background CL2K season batch. Returns { job_id, total }. */
    generateSeasons: req => apiCore.post('/cl2k-maker/generate-seasons', req),

    /** Poll a background season batch's progress. */
    seasonsStatus: jobId => apiCore.get(`/cl2k-maker/seasons-status/${jobId}`, { useCache: false }),

    /** Re-text a poster: AI-erase the old text, redraw in CL2K font. `preview=true`
     *  returns {preview_b64}. `opts` spreads last, so a caller `timeout` overrides
     *  AI_TIMEOUT_MS — no caller does today, and a short one would abort mid-edit. */
    retext: (req, opts) =>
        apiCore.post('/cl2k-maker/retext', req, { timeout: AI_TIMEOUT_MS, ...opts }),

    /** Detect text regions for mask prefill; returns regions + a white-is-text mask.
     *  Long timeout: a 4K upload plus OCR outlasts the 30s default. */
    detectText: req => apiCore.post('/cl2k-maker/detect-text', req, { timeout: AI_TIMEOUT_MS }),

    /** Shrink a brushed erase-mask to the glyph strokes, so the inpainter fills thin
     *  gaps sharply rather than one blurry block. Local compute, but long timeout. */
    tightenMask: req => apiCore.post('/cl2k-maker/tighten-mask', req, { timeout: AI_TIMEOUT_MS }),

    /** Start a background File-as-is season batch (one source poster, re-filed per
     *  season with that season's band). Returns { job_id, total }; poll seasonsStatus. */
    retextSeasons: req => apiCore.post('/cl2k-maker/retext-seasons', req),

    /** Fetch TMDB external ids (tvdb_id + imdb_id) for a picked title. */
    externalIds: (tmdbId, type = 'movie', { tvdbId, imdbId } = {}) =>
        apiCore.get(
            `/cl2k-maker/external-ids?${qs({ tmdb_id: tmdbId, type, tvdb_id: tvdbId, imdb_id: imdbId })}`,
            {
                useCache: true,
                cacheTTL: 5 * 60 * 1000,
            }
        ),

    /** Whether Drive upload is enabled and has a usable Sync GDrive OAuth token. */
    uploadStatus: () => apiCore.get('/cl2k-maker/upload-status', { useCache: false }),
};

export { ENCODE };
