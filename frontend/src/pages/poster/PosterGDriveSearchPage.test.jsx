/** The sync toasts repeat the server's reply: a queued job is not a finished sync. */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

const posters = {
    searchGoogleDrive: vi.fn(() =>
        Promise.resolve({ data: { sources: [{ name: 'Movies', last_updated: null }] } })
    ),
    syncGDriveFolders: vi.fn(),
};
const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };

vi.mock('../../utils/api/posters.js', () => ({ postersAPI: posters }));
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

const { default: PosterGDriveSearchPage } = await import('./PosterGDriveSearchPage.jsx');

const click = async name => {
    render(
        <MemoryRouter>
            <PosterGDriveSearchPage />
        </MemoryRouter>
    );
    fireEvent.click(await screen.findByRole('button', { name }));
};

describe('PosterGDriveSearchPage sync toasts', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it.each([
        ['Sync all', /^sync all$/i],
        ['one folder', 'Sync Movies'],
    ])('%s shows the server message on success', async (_label, name) => {
        posters.syncGDriveFolders.mockResolvedValue({
            success: true,
            message: "A GDrive sync covering 'Movies' is already running (job 7)",
        });

        await click(name);

        await waitFor(() =>
            expect(toast.success).toHaveBeenCalledWith(
                "A GDrive sync covering 'Movies' is already running (job 7)"
            )
        );
    });

    it.each([
        ['Sync all', /^sync all$/i],
        ['one folder', 'Sync Movies'],
    ])('%s shows the server message when refused', async (_label, name) => {
        const busy =
            "A GDrive sync is already running (job 7); sync 'Movies' again once it finishes";
        posters.syncGDriveFolders.mockRejectedValue(new Error(busy));

        await click(name);

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(busy));
        expect(toast.success).not.toHaveBeenCalled();
    });
});
