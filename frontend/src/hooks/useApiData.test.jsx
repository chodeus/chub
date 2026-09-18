import { renderHook, act, waitFor } from '@testing-library/react';

vi.mock('../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

const { useApiData } = await import('./useApiData.js');

/** A request whose promise this test resolves by hand. */
const deferred = () => {
    let settle;
    const promise = new Promise(resolve => {
        settle = resolve;
    });
    return { promise, settle };
};

describe('useApiData cancellation', () => {
    it('drops the loading state when a request is cancelled', async () => {
        const pending = deferred();
        const { result } = renderHook(() =>
            useApiData({ apiFunction: () => pending.promise, options: { showErrorToast: false } })
        );
        expect(result.current.isLoading).toBe(true);

        act(() => {
            result.current.cancel();
        });

        // The in-flight .finally is sequence-guarded and will not run, so cancel
        // has to clear the spinner itself.
        expect(result.current.isLoading).toBe(false);

        await act(async () => {
            pending.settle({ value: 1 });
        });
        expect(result.current.data).toBeNull();
    });

    it('stays out of the loading state when cancelled before the request starts', async () => {
        const pending = deferred();
        const apiFunction = vi.fn(() => pending.promise);
        const { result } = renderHook(() =>
            useApiData({ apiFunction, options: { showErrorToast: false } })
        );

        act(() => {
            result.current.cancel();
        });
        // Let the scheduled startup microtask run; it must find itself superseded.
        await act(async () => {});

        expect(result.current.isLoading).toBe(false);
    });

    it('cancels a scheduled retry when the caller clears', async () => {
        vi.useFakeTimers();
        const apiFunction = vi
            .fn()
            .mockRejectedValueOnce(new TypeError('network'))
            .mockResolvedValue({ value: 'late' });
        const { result } = renderHook(() =>
            useApiData({
                apiFunction,
                options: { retryAttempts: 1, retryDelay: 50, showErrorToast: false },
            })
        );
        await act(async () => {});

        act(() => {
            result.current.clear();
        });
        await act(async () => {
            vi.advanceTimersByTime(200);
        });

        expect(result.current.data).toBeNull();
        vi.useRealTimers();
    });

    it('abandons the in-flight request when dependencies change', async () => {
        const pending = deferred();
        const apiFunction = vi.fn(() => pending.promise);
        const { result, rerender } = renderHook(
            ({ id }) =>
                useApiData({
                    apiFunction,
                    dependencies: [id],
                    options: { immediate: false, showErrorToast: false },
                }),
            { initialProps: { id: 1 } }
        );

        act(() => {
            result.current.execute();
        });
        await waitFor(() => expect(result.current.isLoading).toBe(true));

        rerender({ id: 2 });
        await act(async () => {
            pending.settle({ value: 'stale' });
        });

        // With immediate false nothing re-runs to bump the sequence, so the cleanup must.
        expect(result.current.data).toBeNull();
        expect(result.current.isLoading).toBe(false);
    });

    it('does not let an in-flight response repopulate cleared data', async () => {
        // Each call gets its own promise, so the second request is genuinely pending.
        let pending = deferred();
        const { result } = renderHook(() =>
            useApiData({ apiFunction: () => pending.promise, options: { showErrorToast: false } })
        );

        await act(async () => {
            pending.settle({ value: 'loaded' });
        });
        await waitFor(() => expect(result.current.data).toEqual({ value: 'loaded' }));

        pending = deferred();
        act(() => {
            result.current.execute();
        });
        await waitFor(() => expect(result.current.isLoading).toBe(true));

        act(() => {
            result.current.clear();
        });
        expect(result.current.data).toBeNull();

        await act(async () => {
            pending.settle({ value: 'late' });
        });
        expect(result.current.data).toBeNull();
        expect(result.current.isLoading).toBe(false);
    });
});

// Errors are swallowed here, so callers cannot tell a failed refresh from a
// successful one by awaiting it — the resolved value is the only signal.
describe('useApiData execute() outcome', () => {
    it('resolves true when data was committed and false when the request failed', async () => {
        const apiFunction = vi
            .fn()
            .mockResolvedValueOnce({ value: 'ok' })
            // A plain Error is not retryable, so this settles through the catch.
            .mockRejectedValueOnce(new Error('boom'));
        const { result } = renderHook(() =>
            useApiData({
                apiFunction,
                options: { immediate: false, showErrorToast: false, retryAttempts: 0 },
            })
        );

        let committed;
        await act(async () => {
            committed = await result.current.execute();
        });
        expect(committed).toBe(true);
        expect(result.current.data).toEqual({ value: 'ok' });

        let failed;
        await act(async () => {
            failed = await result.current.execute();
        });
        expect(failed).toBe(false);
        // The previous data is left in place, which is why the caller must not
        // drop its optimistic value on a resolved-but-failed refresh.
        expect(result.current.data).toEqual({ value: 'ok' });
    });
});
