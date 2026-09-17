/** Guards that a re-run effect re-arms isMountedRef instead of dropping every response. */
import { StrictMode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';

vi.mock('../contexts/ToastContext.jsx', () => {
    // One stable object: a fresh toast per render would churn the effect deps.
    const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };
    return { useToast: () => toast };
});

vi.mock('../utils/api/modules.js', () => ({
    modulesAPI: { fetchRunStates: vi.fn(), runModule: vi.fn() },
}));

const { modulesAPI } = await import('../utils/api/modules.js');
const { useModuleExecution } = await import('./useModuleExecution.js');

describe('useModuleExecution', () => {
    beforeEach(() => modulesAPI.fetchRunStates.mockReset());

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
});
