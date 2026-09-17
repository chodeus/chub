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
import { streamTokenParam } from './streamAuth.js';

const ENCODE = encodeURIComponent;

const withAuthQuery = () => {
    const params = new URLSearchParams();
    const jwt = streamTokenParam();
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
     * Build a preview URL for `<img src>` with the short-lived stream token.
     * Never the session JWT: a URL leaks into logs and history.
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
