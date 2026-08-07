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

describe('apiCore.combineSignals relay fallback (no AbortSignal.any)', () => {
    let saved;
    beforeEach(() => {
        // Node has AbortSignal.any, so the relay branch is otherwise never run.
        saved = AbortSignal.any;
        AbortSignal.any = undefined;
    });
    afterEach(() => {
        AbortSignal.any = saved;
    });

    it('still aborts from either source', () => {
        const timeout = new AbortController();
        const caller = new AbortController();
        const combined = apiCore.combineSignals(timeout.signal, caller.signal);
        expect(combined.aborted).toBe(false);
        timeout.abort();
        expect(combined.aborted).toBe(true);
    });

    it('detaches from the surviving source, so a reused caller signal is not pinned', () => {
        const timeout = new AbortController();
        const caller = new AbortController();
        const remove = vi.spyOn(caller.signal, 'removeEventListener');

        apiCore.combineSignals(timeout.signal, caller.signal);
        timeout.abort(); // the OTHER source fires

        // The regression: `once` only clears the listener that fired, leaving one
        // attached to the long-lived caller signal for every request it made.
        expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    });

    it('releases the listener after a SUCCESSFUL request, not just an aborted one', async () => {
        // The gap in the first fix: on success neither signal ever aborts, so the
        // detach never ran and the listener sat on the caller signal until the
        // 30s timeout fired.
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => jsonResponse())
        );
        const caller = new AbortController();
        const remove = vi.spyOn(caller.signal, 'removeEventListener');

        await apiCore.makeRequest('/ok', { signal: caller.signal });

        expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
        vi.unstubAllGlobals();
    });

    it('does not accumulate listeners across many SUCCESSFUL requests', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => jsonResponse())
        );
        const caller = new AbortController();
        const add = vi.spyOn(caller.signal, 'addEventListener');
        const remove = vi.spyOn(caller.signal, 'removeEventListener');

        for (let i = 0; i < 4; i++) {
            await apiCore.makeRequest(`/ok${i}`, { signal: caller.signal });
        }
        expect(add).toHaveBeenCalledTimes(4);
        expect(remove).toHaveBeenCalledTimes(4);
        vi.unstubAllGlobals();
    });

    it('does not accumulate listeners on a caller signal reused across requests', () => {
        const caller = new AbortController();
        const add = vi.spyOn(caller.signal, 'addEventListener');
        const remove = vi.spyOn(caller.signal, 'removeEventListener');

        for (let i = 0; i < 5; i++) {
            const timeout = new AbortController();
            apiCore.combineSignals(timeout.signal, caller.signal);
            timeout.abort();
        }
        expect(add).toHaveBeenCalledTimes(5);
        expect(remove).toHaveBeenCalledTimes(5); // one detach per completed request
    });
});

describe('apiCore.get request sharing', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        apiCore.clearCache();
    });

    it('does not let one caller abort a request shared with another', async () => {
        // Both callers hit the same URL; an AbortSignal stringifies to {} so they
        // collapse onto one tracker key. A's abort must not reject B.
        let settle;
        const fetchMock = vi.fn(
            (_url, opts) =>
                new Promise((resolve, reject) => {
                    settle = () => resolve(jsonResponse({ v: 1 }));
                    opts.signal.addEventListener(
                        'abort',
                        () => {
                            const err = new Error('aborted');
                            err.name = 'AbortError';
                            reject(err);
                        },
                        { once: true }
                    );
                })
        );
        vi.stubGlobal('fetch', fetchMock);

        const a = new AbortController();
        const pendingA = apiCore.get('/shared', { useCache: false, signal: a.signal });
        const pendingB = apiCore.get('/shared', {
            useCache: false,
            signal: new AbortController().signal,
        });

        a.abort();
        await expect(pendingA).rejects.toMatchObject({ name: 'AbortError' });

        settle();
        await expect(pendingB).resolves.toEqual({ v: 1 });
        expect(fetchMock).toHaveBeenCalledTimes(2); // each got its own request
    });

    it('still de-duplicates concurrent GETs when no signal is passed', async () => {
        const fetchMock = vi.fn(async () => jsonResponse({ v: 2 }));
        vi.stubGlobal('fetch', fetchMock);
        const [x, y] = await Promise.all([
            apiCore.get('/dedupe', { useCache: false }),
            apiCore.get('/dedupe', { useCache: false }),
        ]);
        expect(x).toEqual({ v: 2 });
        expect(y).toEqual({ v: 2 });
        expect(fetchMock).toHaveBeenCalledTimes(1);
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

    it('hands fetch a live combined signal and leaves other options intact', async () => {
        // Sampled INSIDE the call: makeRequest aborts its timeout controller in a
        // finally to release listeners, so the signal is aborted once it returns.
        let seen;
        const fetchMock = vi.fn(async (_url, opts) => {
            seen = { signal: opts.signal, aborted: opts.signal.aborted, method: opts.method };
            return jsonResponse();
        });
        vi.stubGlobal('fetch', fetchMock);
        const caller = new AbortController();
        await apiCore.makeRequest('/x', { signal: caller.signal, method: 'GET' });
        expect(seen.signal).toBeInstanceOf(AbortSignal);
        expect(seen.aborted).toBe(false);
        expect(seen.method).toBe('GET');
    });
});
