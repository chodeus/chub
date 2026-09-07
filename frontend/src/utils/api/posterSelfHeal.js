// Poster Self-Heal API client — review surface for the poster_self_heal module.
import { apiCore } from './core.js';

export const posterSelfHealAPI = {
    listReviews: (options = {}) =>
        apiCore.get('/poster-self-heal/reviews', { ...options, useCache: false }),
    count: () => apiCore.get('/poster-self-heal/count', { useCache: false }),
    // Forwards options (e.g. an AbortSignal) so a caller can cancel on unmount.
    // useCache goes LAST — coverage is live config state, so a caller must not be
    // able to turn caching on and serve a stale picture of what's being healed.
    coverage: (options = {}) =>
        apiCore.get('/poster-self-heal/coverage', { ...options, useCache: false }),
    apply: id => apiCore.post(`/poster-self-heal/reviews/${id}/apply`),
    dismiss: id => apiCore.post(`/poster-self-heal/reviews/${id}/dismiss`),
};
