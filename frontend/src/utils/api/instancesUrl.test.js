/** Guards that a Plex instance name cannot re-shape the request URL. */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./core.js', () => ({
    apiCore: {
        get: vi.fn(),
        patch: vi.fn(async () => ({ success: true })),
        clearCache: vi.fn(),
    },
}));

const { apiCore } = await import('./core.js');
const { instancesAPI } = await import('./instances.js');

afterEach(() => {
    apiCore.get.mockReset();
    apiCore.patch.mockReset();
    apiCore.clearCache.mockReset();
});

describe('instance names are encoded as one path segment', () => {
    it('does not let a slash add a path segment on fetch', () => {
        instancesAPI.fetchPlexLibraries('4k/movies');

        expect(apiCore.get.mock.calls.at(-1)[0]).toBe('/plex/4k%2Fmovies/libraries');
    });

    it('does not let a question mark start a query string on fetch', () => {
        instancesAPI.fetchPlexLibraries('main?x=1');

        expect(apiCore.get.mock.calls.at(-1)[0]).toBe('/plex/main%3Fx%3D1/libraries');
    });

    it('invalidates the same key it fetched', async () => {
        await instancesAPI.updateInstanceLibraries('4k/movies', ['Films']);

        expect(apiCore.patch.mock.calls.at(-1)[0]).toBe('/plex/4k%2Fmovies/libraries');
        // A raw name here would clear a key nothing was ever cached under.
        expect(apiCore.clearCache).toHaveBeenCalledWith('/plex/4k%2Fmovies/libraries');
    });
});
