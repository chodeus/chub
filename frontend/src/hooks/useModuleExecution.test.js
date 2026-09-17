/** Guards that a re-run effect re-arms isMountedRef and that only the newest load commits. */
import { StrictMode } from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';

// One stable object: a fresh toast per render would churn the effect deps.
const toast = vi.hoisted(() => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
}));

vi.mock('../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

vi.mock('../utils/api/modules.js', () => ({
    modulesAPI: { fetchRunStates: vi.fn(), runModule: vi.fn() },
}));

const { modulesAPI } = await import('../utils/api/modules.js');
const { useModuleExecution } = await import('./useModuleExecution.js');

/** A request this test settles by hand. */
const deferred = () => {
    let settle;
    const promise = new Promise(resolve => {
        settle = resolve;
    });
    return { promise, settle };
};

describe('useModuleExecution', () => {
    beforeEach(() => {
        modulesAPI.fetchRunStates.mockReset();
        Object.values(toast).forEach(fn => fn.mockReset());
    });

    it('commits run states under StrictMode’s setup-cleanup-setup', async () => {
        modulesAPI.fetchRunStates.mockResolvedValue({
            data: { border_replacerr: { status: 'running' } },
        });

        const { result } = renderHook(() => useModuleExecution(), { wrapper: StrictMode });

        await waitFor(() =>
            expect(result.current.runStates.border_replacerr?.status).toBe('running')
        );
    });

    it('reports a module started elsewhere as running', async () => {
        modulesAPI.fetchRunStates.mockResolvedValue({
            data: { poster_renamerr: { status: 'running' } },
        });

        const { result } = renderHook(() => useModuleExecution(), { wrapper: StrictMode });

        await waitFor(() => expect(result.current.isRunning('poster_renamerr')).toBe(true));
    });

    it('ignores a stale load that resolves after a newer one', async () => {
        const first = deferred();
        const second = deferred();
        modulesAPI.fetchRunStates
            .mockReturnValueOnce(first.promise)
            .mockReturnValueOnce(second.promise);
        const { result } = renderHook(() => useModuleExecution());

        act(() => {
            result.current.refreshData();
        });
        await act(async () => second.settle({ data: { beta: { status: 'running' } } }));
        await act(async () => first.settle({ data: { alpha: { status: 'running' } } }));

        expect(result.current.runStates.beta?.status).toBe('running');
        expect(result.current.runStates.alpha).toBeUndefined();
    });
});
