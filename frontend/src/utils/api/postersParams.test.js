/** Guards that an explicit limit/offset of 0 reaches the query string at every site. */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./core.js', () => ({
    apiCore: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('./streamAuth.js', () => ({
    streamTokenParam: () => '',
    streamAuthDisabled: () => true,
    ensureStreamToken: async () => '',
    subscribeStreamToken: () => () => {},
}));

const { apiCore } = await import('./core.js');
const { postersAPI } = await import('./posters.js');

/** The URL the client passed to apiCore.get on its most recent call. */
const lastUrl = () => apiCore.get.mock.calls.at(-1)[0];

afterEach(() => apiCore.get.mockReset());

describe('explicit zero paging values survive', () => {
    it('sends offset=0 from browsePosters', () => {
        postersAPI.browsePosters({ limit: 0, offset: 0 });

        expect(lastUrl()).toContain('offset=0');
        expect(lastUrl()).toContain('limit=0');
    });

    it('sends offset=0 from listPlexMetadataByMedia', () => {
        postersAPI.listPlexMetadataByMedia({ limit: 0, offset: 0 });

        expect(lastUrl()).toContain('offset=0');
        expect(lastUrl()).toContain('limit=0');
    });

    it('sends offset=0 from listPlexMetadataBloat', () => {
        postersAPI.listPlexMetadataBloat({ limit: 0, offset: 0 });

        expect(lastUrl()).toContain('offset=0');
        expect(lastUrl()).toContain('limit=0');
    });

    it('still omits paging params that were not supplied', () => {
        postersAPI.listPlexMetadataBloat({});

        expect(lastUrl()).not.toContain('limit=');
        expect(lastUrl()).not.toContain('offset=');
    });
});
