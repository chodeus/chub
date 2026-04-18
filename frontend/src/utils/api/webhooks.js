/**
 * CHUB Webhooks API Module
 *
 * Handles webhook status monitoring and manual processing triggers
 * for unmatched assets and cleanarr operations.
 */

import { apiCore } from './core.js';

export const webhooksAPI = {
    /**
     * Get unmatched assets webhook status
     * @returns {Promise<Object>} Status with summary and active state
     */
    getUnmatchedStatus: () => {
        return apiCore.get('/webhooks/unmatched/status', {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * Trigger unmatched assets processing
     * @returns {Promise<Object>} Processing response with job_id
     */
    processUnmatched: () => {
        return apiCore.post('/webhooks/unmatched/process');
    },

    /**
     * Get cleanarr (orphaned poster cleanup) webhook status
     * @returns {Promise<Object>} Status with orphaned_count and summary
     */
    getCleanarrStatus: () => {
        return apiCore.get('/webhooks/cleanarr/status', {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * Trigger cleanarr orphaned poster cleanup
     * @returns {Promise<Object>} Processing response
     */
    processCleanarr: () => {
        return apiCore.post('/webhooks/cleanarr/process');
    },
};
