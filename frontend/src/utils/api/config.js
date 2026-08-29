/**
 * CHUB Configuration API Module
 *
 * Handles configuration management operations using REAL CHUB endpoints:
 * - GET /api/config - Fetch complete or sectioned configuration
 * - POST /api/config - Update configuration
 */

import { apiCore } from './core.js';

/**
 * Configuration API client matching actual CHUB backend endpoints
 */
export const configAPI = {
    /**
     * Fetch complete configuration or specific section
     * @param {Object} options - Request options
     * @param {string} options.section - Optional section name (e.g., 'instances', 'modules')
     * @param {boolean} options.useCache - Use cached data (default: true)
     * @returns {Promise<Object>} Configuration data
     */
    fetchConfig: (options = {}) => {
        const { section, ...coreOptions } = options;
        const url = section ? `/config?section=${encodeURIComponent(section)}` : '/config';

        return apiCore.get(url, {
            useCache: true,
            cacheTTL: 10 * 60 * 1000, // 10 minutes cache for config
            ...coreOptions,
        });
    },

    /**
     * Update configuration
     * @param {Object} configData - Configuration data to update
     * @returns {Promise<Object>} Update response
     */
    updateConfig: configData => {
        return apiCore.post('/config', configData);
    },

    /**
     * Fetch specific configuration section
     * @param {string} section - Section name (e.g., 'instances', 'modules', 'notifications')
     * @param {Object} options - Request options
     * @returns {Promise<Object>} Section configuration data
     */
    fetchSection: (section, options = {}) => {
        return configAPI.fetchConfig({ section, ...options });
    },

    /**
     * Reveal one configured secret's real value on demand.
     *
     * Every config read redacts secrets to "********"; this hits the dedicated
     * GET /api/config/secret endpoint (JWT-gated, no-store) to fetch a single
     * secret when the user clicks the "show" eye toggle. Never cached.
     *
     * @param {string} path - Dotted config path, e.g. 'tmdb.apikey'
     * @returns {Promise<Object>} Response whose data.value is the real secret
     */
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
