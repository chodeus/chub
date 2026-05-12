/**
 * Border Replacerr API client.
 *
 * Powers the Border Replacerr page in the UI:
 * - GET  /api/border-replacerr/preview/options — holiday dropdown options
 * - POST /api/border-replacerr/preview — generate composites; returns tokens
 * - GET  /api/border-replacerr/preview/file/{token}.jpg — composite bytes
 * - GET  /api/border-replacerr/presets — canonical holiday preset catalogue
 * - GET  /api/border-replacerr/borders/{holiday} — bundled + user variants
 * - GET  /api/border-replacerr/borders/{holiday}/{source}/{name}.png — thumbs
 *
 * Image endpoints are consumed directly via <img src=...> using the URL
 * helpers below.
 */

import { apiCore } from './core.js';

const ENCODE = encodeURIComponent;

const withAuthQuery = () => {
    const params = new URLSearchParams();
    const jwt = localStorage.getItem('chub-auth-token');
    if (jwt) params.set('token', jwt);
    return params.toString();
};

export const borderReplacerrAPI = {
    /**
     * Fetch holiday dropdown options for the preview section.
     */
    fetchOptions: async () => {
        return apiCore.get('/border-replacerr/preview/options', {
            useCache: false,
        });
    },

    /**
     * Generate fresh preview composites for the chosen palette.
     * @param {Object} params
     * @param {number} [params.count=6] - How many composites to generate.
     * @param {string} [params.holiday='current'] - 'default', 'current', or a holiday name.
     */
    generatePreview: async ({ count = 6, holiday = 'current' } = {}) => {
        const qs = new URLSearchParams({
            count: String(count),
            holiday,
        });
        return apiCore.post(`/border-replacerr/preview?${qs.toString()}`, {});
    },

    /**
     * Build the URL for a generated preview composite. The browser fetches
     * the bytes through the standard <img> mechanism, which can't send an
     * Authorization header — so we append the JWT as a `token` query param
     * (the auth middleware accepts both header- and query-param tokens).
     * Mirrors the same pattern postersAPI.getPreviewUrl uses.
     */
    fileUrl: token => {
        const qs = withAuthQuery();
        return `/api/border-replacerr/preview/file/${token}.jpg${qs ? `?${qs}` : ''}`;
    },

    /**
     * Fetch the canonical holiday preset catalogue (name, schedule, colors).
     */
    fetchPresets: async () => {
        return apiCore.get('/border-replacerr/presets', {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /**
     * List bundled + user border variants for a holiday by display name.
     */
    fetchBorders: async holiday => {
        return apiCore.get(`/border-replacerr/borders/${ENCODE(holiday)}`, {
            useCache: false,
        });
    },

    /**
     * Thumbnail URL for a single variant. ``source`` is 'bundled' or 'user'.
     */
    thumbnailUrl: (holiday, source, name) => {
        const qs = withAuthQuery();
        const path = `/api/border-replacerr/borders/${ENCODE(holiday)}/${ENCODE(source)}/${ENCODE(name)}.png`;
        return qs ? `${path}?${qs}` : path;
    },
};
