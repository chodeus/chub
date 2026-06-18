/**
 * CL2K Poster Maker API client.
 *
 * Powers the CL2K Poster Maker page. Entry points (TMDB title search, ID/URL
 * paste, Unmatched-Assets deep link) all resolve to a tmdb_id + kind; the art
 * picker lists every logo/backdrop; preview renders without saving; generate
 * writes the poster into the configured source_dir and records provenance.
 *
 *   GET  /api/cl2k-maker/search            TMDB title search
 *   GET  /api/cl2k-maker/resolve           tvdb/imdb id -> tmdb id
 *   GET  /api/cl2k-maker/images            all TMDB logos + backdrops (picker)
 *   GET  /api/cl2k-maker/fanart-images     fanart.tv logo + background (picker)
 *   POST /api/cl2k-maker/preview           render to JPEG, no save (binary)
 *   POST /api/cl2k-maker/generate          render + write + cache + provenance
 *   GET  /api/cl2k-maker/generated         provenance (recent)
 *   POST /api/cl2k-maker/psd-export        layered .psd (binary)
 *   POST /api/cl2k-maker/generate-seasons  generate posters for many seasons
 *   POST /api/cl2k-maker/upload-generate   render from a cleaned backdrop (file)
 *   POST /api/cl2k-maker/upload-poster     file a finished poster as-is (file)
 *
 * /preview and /psd-export return raw bytes, so they bypass apiCore (which reads
 * the body as JSON/text) and use a small fetch helper that returns a Blob.
 */

import { apiCore } from './core.js';

const ENCODE = encodeURIComponent;
const TOKEN_STORAGE_KEY = 'chub-auth-token';

// Client timeout for AI-bound calls (OpenAI text removal, PSD flatten). Must be
// LONGER than the backend ai_timeout (default 120s) so the backend's own error
// surfaces instead of a silent client-side abort.
const AI_TIMEOUT_MS = 180000;

const qs = params => {
    const sp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
    });
    return sp.toString();
};

/**
 * POST JSON and return the raw response body as a Blob. Used for the binary
 * preview / .psd endpoints, which apiCore would corrupt by reading as text.
 * Mirrors apiCore's Bearer-token injection. `signal` (optional AbortSignal)
 * cancels the request — live previews abort a stale render when the sliders
 * move again instead of letting requests pile up on the backend.
 */
const postBlob = async (path, body, { signal } = {}) => {
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

    /** All TMDB logos + backdrops for the art picker. */
    images: (tmdbId, type = 'movie') =>
        apiCore.get(`/cl2k-maker/images?${qs({ tmdb_id: tmdbId, type })}`, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        }),

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
    seasonImages: (tmdbId, seasonNumber) =>
        apiCore.get(
            `/cl2k-maker/season-images?${qs({ tmdb_id: tmdbId, season_number: seasonNumber })}`,
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

    /** Trimmed + whitened logo (b64 PNG + natural size + max_width) for the live
     *  overlay. `req` = { logo_path } or { logo_b64 }. */
    logoProcessed: req => apiCore.post('/cl2k-maker/logo-processed', req),

    /** Render a preview JPEG without saving. Returns a Blob. */
    preview: (req, opts) => postBlob('/cl2k-maker/preview', req, opts),

    /** Render + write + cache + record provenance. */
    generate: req => apiCore.post('/cl2k-maker/generate', req),

    /** Render square art (1:1) without saving. Returns a JPEG Blob. */
    squarePreview: (req, opts) => postBlob('/cl2k-maker/square-preview', req, opts),

    /** Render + file square art (`- SquareArt.jpg`). */
    squareGenerate: req => apiCore.post('/cl2k-maker/square-generate', req),

    /** Render background art (16:9) without saving. Returns a JPEG Blob. */
    backgroundPreview: (req, opts) => postBlob('/cl2k-maker/background-preview', req, opts),

    /** Render + file background art (`- Background.jpg`, 1080p or 4K). */
    backgroundGenerate: req => apiCore.post('/cl2k-maker/background-generate', req),

    /** Processed logo asset (transparent PNG) without saving. Returns a PNG Blob.
     *  `req` = { logo_path | logo_b64, whiten }. */
    logoAssetPreview: req => postBlob('/cl2k-maker/logo-asset-preview', req),

    /** File a clear logo as a `- Logo.png` asset (whiten toggles CL2K white). */
    logoAssetGenerate: req => apiCore.post('/cl2k-maker/logo-asset-generate', req),

    /** Extract a white title from a poster into a transparent logo PNG. Returns a
     *  Blob. `req` = { image_b64 | image_path, mask_b64, lo, hi }. */
    extractLogo: req => postBlob('/cl2k-maker/extract-logo', req),

    /** Recently generated posters (provenance). */
    generated: (limit = 200) =>
        apiCore.get(`/cl2k-maker/generated?${qs({ limit })}`, { useCache: false }),

    /** Export the poster as a layered .psd. Returns a Blob. */
    psdExport: req => postBlob('/cl2k-maker/psd-export', req),

    /** Start a background CL2K season batch. Returns { job_id, total }. */
    generateSeasons: req => apiCore.post('/cl2k-maker/generate-seasons', req),

    /** Poll a background season batch's progress. */
    seasonsStatus: jobId => apiCore.get(`/cl2k-maker/seasons-status/${jobId}`, { useCache: false }),

    /** Generate from a manually-cleaned backdrop (multipart). */
    uploadGenerate: (file, meta) => {
        const fd = new FormData();
        fd.append('file', file);
        Object.entries(meta).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') fd.append(k, String(v));
        });
        return apiCore.post('/cl2k-maker/upload-generate', fd);
    },

    /**
     * File a finished poster (multipart). `meta` may include a logo to composite
     * (logo_path or logo_b64), border, save targets (save_local/upload_gdrive),
     * and preview=true to get { preview_b64 } back instead of saving.
     */
    uploadPoster: (file, meta) => {
        const fd = new FormData();
        fd.append('file', file);
        Object.entries(meta).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') fd.append(k, String(v));
        });
        return apiCore.post('/cl2k-maker/upload-poster', fd);
    },

    /**
     * Re-text a finished poster: AI-erase the brushed old text + redraw a label
     * in CL2K font. preview=true returns {preview_b64}; else saves the poster.
     * Uses a long client timeout — the OpenAI gpt-image-1 edit can take 30–120s
     * (backend ai_timeout defaults to 120s). The default 30s client timeout would
     * abort while the backend is still working, surfacing nothing in the logs.
     */
    retext: req => apiCore.post('/cl2k-maker/retext', req, { timeout: AI_TIMEOUT_MS }),

    /** Start a background File-as-is season batch (one source poster, re-filed per
     *  season with that season's band). Returns { job_id, total }; poll seasonsStatus. */
    retextSeasons: req => apiCore.post('/cl2k-maker/retext-seasons', req),

    /** Fetch TMDB external ids (tvdb_id + imdb_id) for a picked title. */
    externalIds: (tmdbId, type = 'movie') =>
        apiCore.get(`/cl2k-maker/external-ids?${qs({ tmdb_id: tmdbId, type })}`, {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        }),

    /** Whether Drive upload is enabled and has a usable Sync GDrive OAuth token. */
    uploadStatus: () => apiCore.get('/cl2k-maker/upload-status', { useCache: false }),
};

export { ENCODE };
