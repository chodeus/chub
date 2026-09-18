/** Nestarr API: detects unmatched and wrongly-nested media, and moves it back.
 *  Unmatched comparison is opt-in per library mapping. */

import { apiCore } from './core.js';

export const nestarrAPI = {
    /** Last run's cached results; persists across page navigations. */
    getResults: () => apiCore.get('/nestarr/results', { useCache: false }),

    /** Scan every instance for nested-media issues. */
    scan: () => apiCore.post('/nestarr/scan', {}, { timeout: 120000 }),

    /** Dry-run a fix: current/target paths and rename info. Same params as `fix`. */
    preview: params => apiCore.post('/nestarr/preview', params),

    /** Move a nested item to its correct path. Takes instance_type, instance_name,
     *  media_id and target_path. */
    fix: params => apiCore.post('/nestarr/fix', params),
};
