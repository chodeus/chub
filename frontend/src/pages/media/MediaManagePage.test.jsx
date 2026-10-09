/** "Refresh cache" must reload the duplicate list only after the refresh job ends:
 *  a reload at enqueue re-caches the pre-refresh list for its whole TTL. */
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';
import { apiCore } from '../../utils/api/core.js';

const media = {
    fetchDuplicates: vi.fn(),
    fetchCollections: vi.fn(),
    refreshLibrary: vi.fn(),
    fetchOrphaned: vi.fn(),
    fetchIncompleteMetadata: vi.fn(),
};
const poll = { pollJobUntilDone: vi.fn() };
const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };

vi.mock('../../utils/api/media.js', () => ({ mediaAPI: media }));
vi.mock('../../utils/api/nestarr.js', () => ({
    nestarrAPI: { getResults: vi.fn(() => Promise.resolve({ data: null })) },
}));
vi.mock('../../utils/jobPoll.js', () => poll);
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

const { default: MediaManagePage } = await import('./MediaManagePage.jsx');

const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

const deferred = () => {
    let resolve;
    const promise = new Promise(r => (resolve = r));
    return { promise, resolve };
};

const clickRefresh = async () => {
    render(<MediaManagePage />);
    await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
};

describe('MediaManagePage Refresh cache', () => {
    let job;
    let clearCache;

    beforeEach(() => {
        job = deferred();
        clearCache = vi.spyOn(apiCore, 'clearCache');
        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [] } });
        media.fetchCollections.mockResolvedValue({ data: { collections: [] } });
        media.refreshLibrary.mockResolvedValue({ data: { job_id: 7 } });
        poll.pollJobUntilDone.mockReturnValue(job.promise);
    });

    it('reloads the duplicate list only after the refresh job ends', async () => {
        await clickRefresh();

        await waitFor(() =>
            expect(poll.pollJobUntilDone).toHaveBeenCalledWith(7, expect.any(Object))
        );
        expect(media.fetchDuplicates).toHaveBeenCalledTimes(1);
        expect(clearCache).not.toHaveBeenCalledWith('/media');

        job.resolve('success');

        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(2));
        expect(clearCache).toHaveBeenCalledWith('/media');
        expect(clearCache.mock.invocationCallOrder.at(-1)).toBeLessThan(
            media.fetchDuplicates.mock.invocationCallOrder[1]
        );
        expect(toast.success).toHaveBeenCalledWith('Cache refreshed');
    });

    it('still reloads, and says so, when the refresh job fails', async () => {
        await clickRefresh();
        job.resolve('error');

        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(2));
        expect(toast.error).toHaveBeenCalledWith('Cache refresh ended: error');
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('stays quiet when the page is left before the job ends', async () => {
        const { unmount } = render(<MediaManagePage />);
        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(1));
        fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
        await waitFor(() => expect(poll.pollJobUntilDone).toHaveBeenCalled());

        unmount();
        job.resolve('success');
        await job.promise;

        expect(poll.pollJobUntilDone.mock.calls[0][1].cancelled).toBe(true);
        expect(toast.success).not.toHaveBeenCalled();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('reports a refresh that was never queued', async () => {
        media.refreshLibrary.mockResolvedValue({ data: {} });

        await clickRefresh();

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Cache refresh failed'));
        expect(poll.pollJobUntilDone).not.toHaveBeenCalled();
        expect(media.fetchDuplicates).toHaveBeenCalledTimes(1);
    });
});
