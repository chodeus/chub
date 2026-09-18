/** Border Replacerr API. Its image endpoints are consumed directly via `<img src>`
 *  using the URL helpers below, not fetched. */

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
    /** Holiday dropdown options for the preview section. */
    fetchOptions: async () => {
        return apiCore.get('/border-replacerr/preview/options', {
            useCache: false,
        });
    },

    /** Generate preview composites. `holiday` is 'default', 'current', or a holiday name. */
    generatePreview: async ({ count = 6, holiday = 'current' } = {}) => {
        const qs = new URLSearchParams({
            count: String(count),
            holiday,
        });
        return apiCore.post(`/border-replacerr/preview?${qs.toString()}`, {});
    },

    /** Preview URL for `<img src>`, carrying the short-lived stream token.
     *  Never the session JWT: a URL leaks into logs and history. */
    fileUrl: token => {
        const qs = withAuthQuery();
        return `/api/border-replacerr/preview/file/${token}.jpg${qs ? `?${qs}` : ''}`;
    },

    /** The canonical holiday preset catalogue (name, schedule, colors). */
    fetchPresets: async () => {
        return apiCore.get('/border-replacerr/presets', {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
        });
    },

    /** Bundled and user border variants for a holiday, by display name. */
    fetchBorders: async holiday => {
        return apiCore.get(`/border-replacerr/borders/${ENCODE(holiday)}`, {
            useCache: false,
        });
    },

    /** Thumbnail URL for one variant; `source` is 'bundled' or 'user'. */
    thumbnailUrl: (holiday, source, name) => {
        const qs = withAuthQuery();
        const path = `/api/border-replacerr/borders/${ENCODE(holiday)}/${ENCODE(source)}/${ENCODE(name)}.png`;
        return qs ? `${path}?${qs}` : path;
    },
};
