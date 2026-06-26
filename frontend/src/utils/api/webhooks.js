/**
 * CHUB Webhooks API Module
 *
 * Wiring + observability for the inbound poster webhook. Module-run trigger
 * endpoints (cleanarr/unmatched) are still served by the backend for external
 * automation callers but are not surfaced in the UI; no frontend wrapper is
 * required for them.
 */

import { apiCore } from './core.js';

export const webhooksAPI = {
    /**
     * Get poster-webhook wiring details (path + optional secret) so the UI
     * can build ready-to-paste URLs for Sonarr/Radarr/Tautulli.
     * @returns {Promise<Object>} { poster_add_path, secret_configured, secret }
     */
    getWiring: () => {
        return apiCore.get('/webhooks/wiring', {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },

    /**
     * Summarize recent inbound webhook calls by origin + status.
     * Backed by GET /api/jobs/webhook-origins.
     * @param {number} days - Lookback window (1..90)
     * @returns {Promise<Object>} { total, by_origin: [{ client_host, endpoint, count, last_seen, event_type }], by_status: {...} }
     */
    getWebhookOrigins: (days = 7) => {
        return apiCore.get(`/jobs/webhook-origins?days=${encodeURIComponent(days)}`, {
            useCache: true,
            cacheTTL: 60 * 1000,
        });
    },
};
