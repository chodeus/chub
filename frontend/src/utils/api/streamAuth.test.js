/** Guards that a mint resolving after clearStreamToken cannot commit or strand a newer one. */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

/** A fetch this test settles by hand. */
const deferred = () => {
    let settle;
    const promise = new Promise(resolve => {
        settle = resolve;
    });
    return { promise, settle };
};

const tokenResponse = (token = 'minted', expiresIn = 600) => ({
    ok: true,
    status: 200,
    json: async () => ({ data: { token, expires_in: expiresIn } }),
});

let streamAuth;

beforeEach(async () => {
    vi.resetModules();
    localStorage.setItem('chub-auth-token', 'jwt');
    streamAuth = await import('./streamAuth.js');
});

afterEach(() => {
    // A committed mint arms a ~9.5 min refresh timer, and resetModules does not cancel
    // the previous instance's timers — it would outlive the test.
    streamAuth?.clearStreamToken();
    vi.unstubAllGlobals();
    localStorage.removeItem('chub-auth-token');
});

describe('clearStreamToken invalidates an in-flight mint', () => {
    it('does not restore the cached token after a clear', async () => {
        const pending = deferred();
        vi.stubGlobal(
            'fetch',
            vi.fn(() => pending.promise)
        );

        const inFlight = streamAuth.ensureStreamToken();
        streamAuth.clearStreamToken();
        pending.settle(tokenResponse('stale'));
        await inFlight;

        expect(streamAuth.streamTokenSnapshot()).toBe('');
    });

    it('does not notify subscribers after a clear', async () => {
        const pending = deferred();
        vi.stubGlobal(
            'fetch',
            vi.fn(() => pending.promise)
        );
        const inFlight = streamAuth.ensureStreamToken();
        streamAuth.clearStreamToken();

        // Subscribe only after the clear, so the clear's own notify is not counted.
        const onChange = vi.fn();
        const unsubscribe = streamAuth.subscribeStreamToken(onChange);
        pending.settle(tokenResponse('stale'));
        await inFlight;
        unsubscribe();

        expect(onChange).not.toHaveBeenCalled();
    });

    it('does not clear a newly installed JWT when a stale 401 settles', async () => {
        const pending = deferred();
        vi.stubGlobal(
            'fetch',
            vi.fn(() => pending.promise)
        );

        const inFlight = streamAuth.ensureStreamToken();
        streamAuth.clearStreamToken();
        // The user signs back in while the old request is still open.
        localStorage.setItem('chub-auth-token', 'fresh-jwt');

        pending.settle({
            ok: false,
            status: 401,
            json: async () => ({ error_code: 'AUTH_TOKEN_INVALID' }),
        });
        await inFlight;

        expect(localStorage.getItem('chub-auth-token')).toBe('fresh-jwt');
    });

    it('does not clear a newly installed JWT when the stale body parses after the clear', async () => {
        const responded = deferred();
        const parsed = deferred();
        vi.stubGlobal(
            'fetch',
            vi.fn(() => responded.promise)
        );

        const inFlight = streamAuth.ensureStreamToken();
        // The 401 arrives while this mint is still current, so the early check passes.
        responded.settle({ ok: false, status: 401, json: () => parsed.promise });
        await Promise.resolve();
        await Promise.resolve();

        // The session is replaced while the response body is still parsing.
        streamAuth.clearStreamToken();
        localStorage.setItem('chub-auth-token', 'fresh-jwt');
        parsed.settle({ error_code: 'AUTH_TOKEN_INVALID' });
        await inFlight;

        expect(localStorage.getItem('chub-auth-token')).toBe('fresh-jwt');
    });

    it('lets a mint started after the clear still commit', async () => {
        // The stale chain's finally must not null the newer request.
        const stale = deferred();
        const fresh = deferred();
        const fetchMock = vi
            .fn()
            // Pending, so a third call fails the assertion below rather than throwing.
            .mockImplementation(() => deferred().promise)
            .mockImplementationOnce(() => stale.promise)
            .mockImplementationOnce(() => fresh.promise);
        vi.stubGlobal('fetch', fetchMock);

        const staleCall = streamAuth.ensureStreamToken();
        streamAuth.clearStreamToken();
        const freshCall = streamAuth.ensureStreamToken();

        stale.settle(tokenResponse('stale'));
        await staleCall;

        // Joins the pending mint; a third fetch would mean the stale finally nulled it.
        const joinedCall = streamAuth.ensureStreamToken();
        expect(fetchMock).toHaveBeenCalledTimes(2);

        fresh.settle(tokenResponse('current'));
        await Promise.all([freshCall, joinedCall]);

        expect(streamAuth.streamTokenSnapshot()).toBe('current');
    });
});
