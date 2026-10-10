/** "Refresh cache" reloads the duplicate list only after the refresh job ends. */
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';
import { apiCore } from '../../utils/api/core.js';

const media = {
    fetchDuplicates: vi.fn(),
    fetchDuplicateMembers: vi.fn(),
    fetchCollections: vi.fn(),
    refreshLibrary: vi.fn(),
    fetchOrphaned: vi.fn(),
    fetchIncompleteMetadata: vi.fn(),
};
const poll = { pollJobUntilDone: vi.fn(), POLL_UNREACHABLE: 'unreachable' };
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

    it('reloads a group’s copies after a refresh, even under the same key', async () => {
        const group = { normalized_title: 'samefilm', title: 'Same Film', count: 2, ids: '1,2' };
        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [group] } });
        media.fetchDuplicateMembers.mockResolvedValue({ data: { members: [] } });
        render(<MediaManagePage />);
        fireEvent.click(await screen.findByRole('button', { name: /Same Film/ }));
        await waitFor(() => expect(media.fetchDuplicateMembers).toHaveBeenCalledTimes(1));

        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [{ ...group }] } });
        fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
        job.resolve('success');
        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(2));
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Cache refreshed'));
        fireEvent.click(await screen.findByRole('button', { name: /Same Film/ }));

        await waitFor(() => expect(media.fetchDuplicateMembers).toHaveBeenCalledTimes(2));
    });

    it('drops a copies request that returns after the list reloaded', async () => {
        const group = { normalized_title: 'samefilm', title: 'Same Film', count: 2, ids: '1,2' };
        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [group] } });
        let answerOld;
        media.fetchDuplicateMembers.mockReturnValueOnce(new Promise(r => (answerOld = r)));
        render(<MediaManagePage />);
        fireEvent.click(await screen.findByRole('button', { name: /Same Film/ }));

        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [{ ...group }] } });
        fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
        job.resolve('success');
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Cache refreshed'));
        answerOld({ data: { members: [{ id: 1, path: '/old/copy' }] } });
        media.fetchDuplicateMembers.mockResolvedValue({ data: { members: [] } });
        fireEvent.click(await screen.findByRole('button', { name: /Same Film/ }));

        await waitFor(() => expect(media.fetchDuplicateMembers).toHaveBeenCalledTimes(2));
    });

    it('keeps Resolve unavailable while a refresh is running', async () => {
        const group = { normalized_title: 'samefilm', title: 'Same Film', count: 2, ids: '1,2' };
        const copy = { id: 1, path: '/films/Same Film', live: { size_bytes: 1 } };
        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [group] } });
        media.fetchDuplicateMembers.mockResolvedValue({ data: { members: [copy] } });
        render(<MediaManagePage />);
        const openGroup = async () => {
            fireEvent.click(await screen.findByRole('button', { name: /Same Film/ }));
            return screen.findByRole('button', { name: /Resolve manually/ });
        };
        expect(await openGroup()).toBeEnabled();

        media.fetchDuplicates.mockResolvedValue({ data: { duplicates: [{ ...group }] } });
        fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
        await waitFor(() =>
            expect(screen.getByRole('button', { name: /Resolve manually/ })).toBeDisabled()
        );
        job.resolve('success');
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Cache refreshed'));

        expect(await openGroup()).toBeEnabled();
    });

    it('keeps folder-collision Resolve unavailable until the reloaded list is in', async () => {
        const collision = { id: 9, normalized_title: 'clashfilm', count: 2, folders: '[]' };
        media.fetchDuplicates.mockResolvedValue({
            data: { duplicates: [], folder_collisions: [collision] },
        });
        render(<MediaManagePage />);
        const resolve = () => screen.getByRole('button', { name: /^Resolve$/ });
        await waitFor(() => expect(resolve()).toBeEnabled());

        let finishReload;
        media.fetchDuplicates.mockReturnValue(new Promise(r => (finishReload = r)));
        fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
        await waitFor(() => expect(resolve()).toBeDisabled());
        job.resolve('success');
        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(2));
        const midReload = resolve().disabled;
        finishReload({ data: { duplicates: [], folder_collisions: [{ ...collision }] } });

        await waitFor(() => expect(resolve()).toBeEnabled());
        expect(midReload).toBe(true);
    });

    it('stays quiet when the page is left while the list reloads', async () => {
        const { unmount } = render(<MediaManagePage />);
        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(1));
        let finishReload;
        media.fetchDuplicates.mockReturnValue(new Promise(r => (finishReload = r)));
        fireEvent.click(screen.getByRole('button', { name: /refresh cache/i }));
        job.resolve('success');
        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(2));

        unmount();
        finishReload({ data: { duplicates: [] } });
        await new Promise(r => setTimeout(r, 50));

        expect(toast.success).not.toHaveBeenCalled();
    });

    it('says it lost track of the job when polling gives up, and still reloads', async () => {
        await clickRefresh();
        job.resolve('unreachable');

        await waitFor(() => expect(media.fetchDuplicates).toHaveBeenCalledTimes(2));
        expect(toast.error).toHaveBeenCalledWith(
            'Lost track of the cache refresh job; the list may be out of date'
        );
    });

    it('reports a refresh that was never queued', async () => {
        media.refreshLibrary.mockResolvedValue({ data: {} });

        await clickRefresh();

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Cache refresh failed'));
        expect(poll.pollJobUntilDone).not.toHaveBeenCalled();
        expect(media.fetchDuplicates).toHaveBeenCalledTimes(1);
    });
});
