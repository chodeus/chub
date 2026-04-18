/**
 * CHUB Nestarr API Module
 *
 * Handles nested media detection and resolution:
 * - Scanning for incorrectly nested media folders
 * - Fixing nested items by moving to correct locations
 */

import { apiCore } from './core.js';

/**
 * Nestarr API client for nested media detection
 */
export const nestarrAPI = {
    /**
     * Get cached scan results from the last run (persists across page navigations)
     * @returns {Promise<Object>} Cached results with issues array and scanned_at timestamp
     */
    getResults: () => apiCore.get('/nestarr/results', { useCache: false }),

    /**
     * Scan all instances for nested media issues
     * @returns {Promise<Object>} Scan results with issues array
     */
    scan: () => apiCore.get('/nestarr/scan'),

    /**
     * Preview what a fix would do before executing
     * @param {Object} params - Same as fix params
     * @returns {Promise<Object>} Preview with current/target paths and rename info
     */
    preview: params => apiCore.post('/nestarr/preview', params),

    /**
     * Fix a nested media item by moving it to the correct path
     * @param {Object} params - Fix parameters
     * @param {string} params.instance_type - "radarr" or "sonarr"
     * @param {string} params.instance_name - Instance name
     * @param {number} params.media_id - Media ID to fix
     * @param {string} params.target_path - Target path to move to
     * @returns {Promise<Object>} Fix result
     */
    fix: params => apiCore.post('/nestarr/fix', params),
};
