/** "Sync now" must start a full Labelarr run: the per-item /labelarr/sync endpoint
 *  needs a source instance and media id, so posting it bare could only ever 422. */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const modules = {
    fetchRunStates: vi.fn(() => Promise.resolve({ data: { labelarr: { status: 'idle' } } })),
    runModule: vi.fn(),
};
const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };

vi.mock('../../utils/api/modules.js', () => ({ modulesAPI: modules }));
vi.mock('../../utils/api/config.js', () => ({
    configAPI: {
        fetchConfig: vi.fn(() =>
            Promise.resolve({ data: { labelarr: { mappings: [] }, instances: {} } })
        ),
        updateConfig: vi.fn(),
    },
}));
vi.mock('../../utils/api', () => ({
    instancesAPI: { fetchPlexLibraries: vi.fn(() => Promise.resolve({ data: [] })) },
}));
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));
vi.mock('../../contexts/ConfirmContext.jsx', () => ({ useConfirm: () => vi.fn() }));

const { default: LabelarrPage } = await import('./LabelarrPage.jsx');

const syncNow = async () => {
    render(<LabelarrPage />);
    fireEvent.click(await screen.findByRole('button', { name: /sync now/i }));
};

describe('LabelarrPage Sync now', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('queues a Labelarr module run', async () => {
        modules.runModule.mockResolvedValue({ data: { job_id: 1 } });

        await syncNow();

        await waitFor(() => expect(modules.runModule).toHaveBeenCalledWith('labelarr'));
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Label sync queued'));
    });

    it('says so when the module is disabled', async () => {
        modules.runModule.mockResolvedValue({ data: { disabled: true } });

        await syncNow();

        await waitFor(() =>
            expect(toast.error).toHaveBeenCalledWith(
                'Labelarr is disabled — enable it on the Modules page first'
            )
        );
        expect(toast.success).not.toHaveBeenCalled();
    });
});
