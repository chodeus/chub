/**
 * Border Replacerr preview API client.
 *
 * Powers the Border Replacerr preview page in the UI. Two endpoints:
 * - GET /api/border-replacerr/preview/options — holiday dropdown options
 * - POST /api/border-replacerr/preview — generate composites; returns tokens
 *
 * The composite bytes are served at /api/border-replacerr/preview/file/{token}.jpg;
 * the page consumes those URLs directly via <img src=...>.
 */

import { apiCore } from './core.js';

export const borderReplacerrAPI = {
    /**
     * Fetch holiday dropdown options for the preview page.
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
        const params = new URLSearchParams();
        const jwt = localStorage.getItem('chub-auth-token');
        if (jwt) params.set('token', jwt);
        const qs = params.toString();
        return `/api/border-replacerr/preview/file/${token}.jpg${qs ? `?${qs}` : ''}`;
    },
};
