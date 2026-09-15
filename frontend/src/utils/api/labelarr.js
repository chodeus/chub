/**
 * CHUB Labelarr API Module
 *
 * Handles label sync operations between Radarr/Sonarr and Plex.
 */

import { apiCore } from './core.js';

export const labelarrAPI = {
    /**
     * Trigger label sync from ARR instances to Plex
     * @param {Object} options - Sync options
     * @returns {Promise<Object>} Sync response
     */
    sync: (options = {}) => {
        return apiCore.post('/labelarr/sync', options);
    },
};
