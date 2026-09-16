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
