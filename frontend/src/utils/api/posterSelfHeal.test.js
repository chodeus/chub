/** posterSelfHealAPI option forwarding — callers may pass a signal, but must not
 *  be able to re-enable caching on live coverage state. */
const mockCore = { get: vi.fn(async () => ({ data: {} })), post: vi.fn() };
vi.mock('./core.js', () => ({ apiCore: mockCore }));

const { posterSelfHealAPI } = await import('./posterSelfHeal.js');

describe('posterSelfHealAPI.coverage', () => {
    it('forwards caller options such as an AbortSignal', async () => {
        const signal = new AbortController().signal;
        await posterSelfHealAPI.coverage({ signal });
        expect(mockCore.get).toHaveBeenCalledWith(
            '/poster-self-heal/coverage',
            expect.objectContaining({ signal })
        );
    });

    it('keeps the cache bypass mandatory even if a caller asks for caching', async () => {
        await posterSelfHealAPI.coverage({ useCache: true });
        const [, opts] = mockCore.get.mock.calls[mockCore.get.mock.calls.length - 1];
        // Coverage is live config state — a cached answer would misreport what the
        // healer is about to assess.
        expect(opts.useCache).toBe(false);
    });

    it('works with no arguments at all', async () => {
        await posterSelfHealAPI.coverage();
        const [url, opts] = mockCore.get.mock.calls[mockCore.get.mock.calls.length - 1];
        expect(url).toBe('/poster-self-heal/coverage');
        expect(opts.useCache).toBe(false);
    });
});
