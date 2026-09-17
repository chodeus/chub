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

describe('coercible non-numbers are rejected, not serialized', () => {
    // Number(null), Number('') and Number(true) are all finite, so a coercion
    // check would send limit=null, limit= and limit=true.
    it.each([
        ['null', null],
        ['an empty string', ''],
        ['a boolean', true],
    ])('drops %s from browsePosters', (_, value) => {
        postersAPI.browsePosters({ limit: value, offset: value });

        expect(lastUrl()).not.toContain('limit=');
        expect(lastUrl()).not.toContain('offset=');
    });

    it('drops a non-numeric string rather than sending it', () => {
        postersAPI.listPlexMetadataByMedia({ limit: '25', offset: 'abc' });

        expect(lastUrl()).not.toContain('limit=');
        expect(lastUrl()).not.toContain('offset=');
    });

    it('drops coercible values from listPlexMetadataBloat too', () => {
        postersAPI.listPlexMetadataBloat({ limit: null, offset: '' });

        expect(lastUrl()).not.toContain('limit=');
        expect(lastUrl()).not.toContain('offset=');
    });
});
