/**
 * CHUB Notifications API Module
 *
 * Notifications are modelled as a list of **destinations** (per-channel). Each
 * destination fans out to the modules it should report on:
 *   { id, method: "discord"|"notifiarr", name, enabled,
 *     events: { success, failure }, modules: string[], config: {...} }
 *
 * `modules` holds module keys; the sentinel "__ALL__" means every module.
 * `config` holds method-specific credentials (Discord: webhook/bot_name/color;
 * Notifiarr: webhook/channel_id/color). Secrets round-trip as "********".
 */

import { apiCore } from './core.js';

/** Sentinel stored in a destination's `modules` meaning "every module". */
export const ALL_MODULES = '__ALL__';

export const notificationsAPI = {
    /**
     * Fetch all notification destinations.
     * @returns {Promise<Object>} { data: { destinations: [...] } }
     */
    fetchNotifications: (options = {}) => {
        return apiCore.get('/notifications', {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
            ...options,
        });
    },

    /**
     * Create a new destination.
     * @param {Object} destination - { method, name, enabled, events, modules, config }
     */
    createDestination: destination => {
        return apiCore.post('/notifications/destinations', destination);
    },

    /**
     * Update an existing destination. Secrets sent back as "********" are
     * preserved server-side (not overwritten).
     * @param {string} id - Destination id
     * @param {Object} destination - Full destination payload
     */
    updateDestination: (id, destination) => {
        return apiCore.put(`/notifications/destinations/${id}`, destination);
    },

    /**
     * Delete a destination by id.
     * @param {string} id - Destination id
     */
    deleteDestination: id => {
        return apiCore.delete(`/notifications/destinations/${id}`);
    },

    /**
     * Send a test message for one method + config. Passing `id` lets the server
     * resolve redacted secrets against the saved destination.
     * @param {Object} data - { method, config, id? }
     */
    testDestination: data => {
        return apiCore.post('/notifications/test', data);
    },
};
