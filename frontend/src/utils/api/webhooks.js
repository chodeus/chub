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

    /**
     * Dry-run reconcile of the poster webhook across every Radarr/Sonarr
     * instance. Never returns the secret-bearing URL — only status/drift flags.
     * Base-URL precedence (server-side): explicit baseUrl → saved public_url →
     * auto-detected from an existing *arr webhook → originHint (last resort).
     * @param {Object} [opts]
     * @param {string} [opts.baseUrl] - Explicit base URL to reconcile against (the user's edited value).
     * @param {string} [opts.originHint] - Browser origin, used only as a last-resort fallback.
     * @returns {Promise<Object>} { base_url, detected_base_url, base_url_error?, public_url_configured, secret_configured, notification_name, instances: [{ name, type, status, drift_fields, error, foreign_webhook }] }
     */
    getProvisionStatus: ({ baseUrl, originHint } = {}) => {
        const params = new URLSearchParams();
        if (baseUrl) params.set('base_url', baseUrl);
        if (originHint) params.set('origin_hint', originHint);
        const qs = params.toString();
        return apiCore.get(`/webhooks/provision/status${qs ? `?${qs}` : ''}`, {
            useCache: false,
        });
    },

    /**
     * Create/update CHUB's poster webhook in the selected instances via their
     * own API (?instance= and the secret are baked in server-side).
     * @param {Object} opts
     * @param {string[]} [opts.instances] - instance names, or omit/['all'] for all
     * @param {string} [opts.baseUrl] - arr-reachable CHUB base URL
     * @param {boolean} [opts.includeUpgrade] - also fire on file upgrade
     * @param {boolean} [opts.forceSave] - skip the arr's connection test
     * @returns {Promise<Object>} { instances: [...], base_url }
     */
    provision: ({ instances, baseUrl, includeUpgrade = false, forceSave = false } = {}) => {
        return apiCore.post('/webhooks/provision', {
            instances,
            base_url: baseUrl,
            include_upgrade: includeUpgrade,
            force_save: forceSave,
        });
    },

    /**
     * Delete CHUB's own poster webhook from the selected instances (leaves
     * user-made webhooks untouched).
     * @param {Object} [opts]
     * @param {string[]} [opts.instances] - instance names, or omit/['all'] for all
     * @returns {Promise<Object>} { instances: [...] }
     */
    removeProvision: ({ instances } = {}) => {
        return apiCore.post('/webhooks/provision/remove', { instances });
    },
};
