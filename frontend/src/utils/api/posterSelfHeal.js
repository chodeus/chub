// Poster Self-Heal API client — review surface for the poster_self_heal module.
import { apiCore } from './core.js';

export const posterSelfHealAPI = {
    listReviews: () => apiCore.get('/poster-self-heal/reviews', { useCache: false }),
    count: () => apiCore.get('/poster-self-heal/count', { useCache: false }),
    coverage: () => apiCore.get('/poster-self-heal/coverage', { useCache: false }),
    apply: id => apiCore.post(`/poster-self-heal/reviews/${id}/apply`),
    dismiss: id => apiCore.post(`/poster-self-heal/reviews/${id}/dismiss`),
};
