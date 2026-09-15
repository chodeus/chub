// Regression: deleting GDrive-local rows must clear every cached poster listing,
// including the real GDrive search prefix (not a guessed one).
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiCore } from './core';
import { postersAPI } from './posters';

afterEach(() => {
    vi.restoreAllMocks();
    apiCore.clearCache();
});

describe('deleteGdriveLocal cache invalidation', () => {
    it('clears list, browse and the gdrive search caches on success', async () => {
        apiCore.cache.set('/posters/list?limit=50', { t: 1 });
        apiCore.cache.set('/posters/browse?query=x', { t: 1 });
        apiCore.cache.set('/posters/sources/gdrive/search?q=show', { t: 1 });
        apiCore.cache.set('/posters/unmatched/stats', { t: 1 });

        vi.spyOn(apiCore, 'post').mockResolvedValue({ success: true });

        await postersAPI.deleteGdriveLocal({ location: '/x' });

        expect(apiCore.cache.has('/posters/list?limit=50')).toBe(false);
        expect(apiCore.cache.has('/posters/browse?query=x')).toBe(false);
        expect(apiCore.cache.has('/posters/sources/gdrive/search?q=show')).toBe(false);
        // Unrelated entries survive.
        expect(apiCore.cache.has('/posters/unmatched/stats')).toBe(true);
    });
});
