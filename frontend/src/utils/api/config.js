/** Config API client: GET and POST /api/config. */

import { apiCore } from './core.js';

export const configAPI = {
    /** Fetch the whole config, or one section when `options.section` is set. */
    fetchConfig: (options = {}) => {
        const { section, ...coreOptions } = options;
        const url = section ? `/config?section=${encodeURIComponent(section)}` : '/config';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000, // 10 minutes cache for config
            ...coreOptions,
        });
    },

    /** Update configuration. */
    updateConfig: configData => {
        return apiCore.post('/config', configData);
    },

    /** Fetch one configuration section. */
    fetchSection: (section, options = {}) => {
        return configAPI.fetchConfig({ section, ...options });
    },

    /** The one unredacted secret read — JWT-gated, never cached, by dotted path. */
    revealSecret: path => {
        return apiCore.get(`/config/secret?path=${encodeURIComponent(path)}`, {
            useCache: false,
        });
    },

    // Uncached: the server stats the keyfile, so saving a path changes the answer.
    // `signal` cancels a superseded request. Returns data.shared_client_id.
    fetchGdriveCredentialStatus: signal => {
        return apiCore.get('/config/gdrive-credentials', { useCache: false, signal });
    },
};
