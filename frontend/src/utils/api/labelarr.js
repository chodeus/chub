/** Labelarr API: label sync between Radarr/Sonarr and Plex. */

import { apiCore } from './core.js';

export const labelarrAPI = {
    /** Trigger label sync from the ARR instances to Plex. */
    sync: (options = {}) => {
        return apiCore.post('/labelarr/sync', options);
    },
};
