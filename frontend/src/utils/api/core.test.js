/**
 * apiCore signal handling — a caller-supplied AbortSignal must reach fetch and
 * be able to cancel, without losing the request timeout.
 */
import { apiCore } from './core.js';

const jsonResponse = (data = { ok: true }) => ({
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
});

// fetch that never settles until the signal aborts, so a test can drive timing.
const abortableFetch = () =>
    vi.fn(
        (_url, opts) =>
            new Promise((_resolve, reject) => {
                const signal = opts.signal;
                const fail = () => {
                    const err = new Error('aborted');
                    err.name = 'AbortError';
                    reject(err);
                };
                if (signal.aborted) return fail();
                signal.addEventListener('abort', fail, { once: true });
            })
    );

describe('apiCore.combineSignals', () => {
    it('returns the timeout signal untouched when no caller signal is given', () => {
        const timeout = new AbortController().signal;
        expect(apiCore.combineSignals(timeout, undefined)).toBe(timeout);
    });

    it('aborts when the caller aborts', () => {
        const timeout = new AbortController();
        const caller = new AbortController();
        const combined = apiCore.combineSignals(timeout.signal, caller.signal);
        expect(combined.aborted).toBe(false);
        caller.abort();
        expect(combined.aborted).toBe(true);
    });

    it('aborts when the timeout fires', () => {
        const timeout = new AbortController();
        const caller = new AbortController();
        const combined = apiCore.combineSignals(timeout.signal, caller.signal);
        timeout.abort();
        expect(combined.aborted).toBe(true);
    });

    it('is already aborted when the caller signal arrives aborted', () => {
        const caller = new AbortController();
        caller.abort();
        const combined = apiCore.combineSignals(new AbortController().signal, caller.signal);
        expect(combined.aborted).toBe(true);
    });
});

describe('apiCore.makeRequest signal forwarding', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('passes a signal to fetch that the caller can abort', async () => {
        const fetchMock = abortableFetch();
        vi.stubGlobal('fetch', fetchMock);
        const caller = new AbortController();

        const pending = apiCore.makeRequest('/x', { signal: caller.signal });
        // The regression: makeRequest used to replace the caller signal with its
        // own, so aborting here never reached fetch and this would hang.
        caller.abort();

        await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('reports a caller abort as an abort, not a phantom 408 timeout', async () => {
        vi.stubGlobal('fetch', abortableFetch());
        const caller = new AbortController();
        const pending = apiCore.makeRequest('/x', { signal: caller.signal });
        caller.abort();
        await expect(pending).rejects.toSatisfy(
            err => err.name === 'AbortError' && err.status !== 408
        );
    });

    it('still reports a real timeout as 408 when no caller signal is given', async () => {
        vi.stubGlobal('fetch', abortableFetch());
        // 1ms timeout, no caller signal — the timeout controller must still fire.
        await expect(apiCore.makeRequest('/x', { timeout: 1 })).rejects.toMatchObject({
            status: 408,
        });
    });

    it('does not leak the caller signal into fetch options twice', async () => {
        const fetchMock = vi.fn(async () => jsonResponse());
        vi.stubGlobal('fetch', fetchMock);
        const caller = new AbortController();
        await apiCore.makeRequest('/x', { signal: caller.signal, method: 'GET' });
        const opts = fetchMock.mock.calls[0][1];
        expect(opts.signal).toBeInstanceOf(AbortSignal);
        expect(opts.signal.aborted).toBe(false);
        expect(opts.method).toBe('GET');
    });
});
