import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import NewPresetNotice from './NewPresetNotice.jsx';
import { dismissNewGdrivePresets, fetchNewGdrivePresets } from '../utils/gdrivePresets.js';

vi.mock('../utils/gdrivePresets.js', () => ({
    fetchNewGdrivePresets: vi.fn(),
    dismissNewGdrivePresets: vi.fn(),
}));

const PRESETS = [
    { id: '1NoticeTestAAAAAAAAAAAAAAAAAAAAAA', name: 'MM2K Testcurator', style: 'MM2K' },
    { id: '1NoticeTestBBBBBBBBBBBBBBBBBBBBBB', name: 'Artwork Othercurator', style: 'Artwork' },
];

// The notice sits outside the routes, as it does in Layout, so it survives navigation
const renderApp = () =>
    render(
        <MemoryRouter initialEntries={['/dashboard']}>
            <NewPresetNotice />
            <Routes>
                <Route path="/dashboard" element={<div>Dashboard</div>} />
                <Route
                    path="/settings/modules/sync_gdrive"
                    element={<div>Sync GDrive settings</div>}
                />
            </Routes>
        </MemoryRouter>
    );

describe('NewPresetNotice', () => {
    afterEach(() => vi.clearAllMocks());

    it('lists the new presets and clears them for good on Dismiss', async () => {
        fetchNewGdrivePresets.mockResolvedValue(PRESETS);
        dismissNewGdrivePresets.mockResolvedValue({ success: true, data: [] });
        renderApp();

        const card = await screen.findByRole('region', { name: '2 new GDrive presets' });
        expect(card).toHaveTextContent('MM2K Testcurator');
        expect(card).toHaveTextContent('Artwork Othercurator');

        await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

        expect(dismissNewGdrivePresets).toHaveBeenCalledWith(PRESETS.map(p => p.id));
        await waitFor(() => expect(screen.queryByRole('region')).not.toBeInTheDocument());
    });

    it('keeps the card when the dismiss call fails', async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        fetchNewGdrivePresets.mockResolvedValue(PRESETS.slice(0, 1));
        dismissNewGdrivePresets.mockRejectedValue(new Error('offline'));
        renderApp();

        await screen.findByRole('region', { name: 'New GDrive preset' });
        await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

        expect(
            await screen.findByRole('region', { name: 'New GDrive preset' })
        ).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Dismiss' })).toBeEnabled();
    });

    it('opens Sync GDrive and hides without dismissing', async () => {
        fetchNewGdrivePresets.mockResolvedValue(PRESETS);
        renderApp();

        await userEvent.click(await screen.findByRole('button', { name: 'Open Sync GDrive' }));

        expect(screen.getByText('Sync GDrive settings')).toBeInTheDocument();
        expect(screen.queryByRole('region')).not.toBeInTheDocument();
        expect(dismissNewGdrivePresets).not.toHaveBeenCalled();
    });

    it('renders nothing when there is nothing new', async () => {
        fetchNewGdrivePresets.mockResolvedValue([]);
        renderApp();

        await waitFor(() => expect(fetchNewGdrivePresets).toHaveBeenCalled());
        expect(screen.queryByRole('region')).not.toBeInTheDocument();
    });

    it('renders nothing when the check fails', async () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        fetchNewGdrivePresets.mockRejectedValue(new Error('offline'));
        renderApp();

        await waitFor(() => expect(warn).toHaveBeenCalled());
        expect(screen.queryByRole('region')).not.toBeInTheDocument();
    });
});
