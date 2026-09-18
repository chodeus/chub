/** Notifications API. A destination is one channel fanning out to chosen modules;
 *  its `config` holds method-specific credentials, and secrets round-trip as "********". */

import { apiCore } from './core.js';

/** Sentinel stored in a destination's `modules` meaning "every module". */
export const ALL_MODULES = '__ALL__';

export const notificationsAPI = {
    /** All notification destinations. */
    fetchNotifications: (options = {}) => {
        return apiCore.get('/notifications', {
            useCache: true,
            cacheTTL: 5 * 60 * 1000,
            ...options,
        });
    },

    /** Create a destination from { method, name, enabled, events, modules, config }. */
    createDestination: destination => {
        return apiCore.post('/notifications/destinations', destination);
    },

    /** Update a destination. Secrets sent back as "********" are preserved
     *  server-side, not overwritten. */
    updateDestination: (id, destination) => {
        return apiCore.put(`/notifications/destinations/${id}`, destination);
    },

    /** Delete a destination by id. */
    deleteDestination: id => {
        return apiCore.delete(`/notifications/destinations/${id}`);
    },

    /** Test one method + config. Passing `id` lets the server resolve redacted
     *  secrets against the saved destination. */
    testDestination: data => {
        return apiCore.post('/notifications/test', data);
    },
};
