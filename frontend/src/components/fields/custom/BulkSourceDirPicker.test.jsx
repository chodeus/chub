/** Guards the failed-load message: a failed fetch must not read as "nothing configured". */
import { render, screen, fireEvent } from '@testing-library/react';

const search = vi.hoisted(() => ({ impl: null, options: null }));

vi.mock('../../../utils/api/posters.js', () => ({
    postersAPI: {
        searchGoogleDrive: (params, options) => {
            search.options = options;
            return search.impl();
        },
    },
}));

const { BulkSourceDirPicker } = await import('./BulkSourceDirPicker.jsx');

const openPanel = () => fireEvent.click(screen.getByRole('button', { name: /Bulk-add/ }));

describe('BulkSourceDirPicker', () => {
    it('reports a failed load instead of an empty drive list', async () => {
        search.impl = () => Promise.reject(new Error('network down'));
        render(<BulkSourceDirPicker directories={[]} onChange={() => {}} />);
        openPanel();

        expect(await screen.findByText(/Couldn't load/)).toBeInTheDocument();
        expect(screen.queryByText(/No Google Drives configured/)).not.toBeInTheDocument();
    });

    it('still reports an empty list as not configured', async () => {
        search.impl = () => Promise.resolve({ data: { sources: [] } });
        render(<BulkSourceDirPicker directories={[]} onChange={() => {}} />);
        openPanel();

        expect(await screen.findByText(/No Google Drives configured/)).toBeInTheDocument();
    });

    it('aborts the in-flight search when it unmounts', () => {
        search.impl = () => new Promise(() => {});
        const { unmount } = render(<BulkSourceDirPicker directories={[]} onChange={() => {}} />);

        expect(search.options.signal.aborted).toBe(false);
        unmount();

        expect(search.options.signal.aborted).toBe(true);
    });
});
