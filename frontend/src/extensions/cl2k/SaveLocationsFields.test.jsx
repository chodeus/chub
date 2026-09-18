import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { useState } from 'react';

// The factory wraps the spy rather than passing it: vitest.config sets
// mockReset, which would strip an implementation handed over directly.
const mockPost = vi.fn();
vi.mock('../../utils/api/core', () => ({ apiCore: { post: (...args) => mockPost(...args) } }));

const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() };
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

const { Cl2kGdriveUploadsField } = await import('./SaveLocationsFields.jsx');

const SUBFOLDERS = [
    { image_type: 'logo', name: 'Logos', folder_id: 'L1' },
    { image_type: 'background', name: 'Backgrounds', folder_id: 'B1' },
    { image_type: 'squareart', name: 'Square', folder_id: 'S1' },
];

const Harness = ({ initial }) => {
    const [value, setValue] = useState(initial);
    return <Cl2kGdriveUploadsField value={value} onChange={setValue} />;
};

const names = () => screen.getAllByLabelText('Location name').map(i => i.value);
const splitButtons = () => screen.getAllByRole('button', { name: /Split by type/ });

describe('Cl2kGdriveUploadsField', () => {
    it('splits the row whose button was pressed, not the first sharing its folder id', async () => {
        mockPost.mockResolvedValue({ data: { subfolders: SUBFOLDERS } });
        render(
            <Harness
                initial={[
                    { name: 'A', folder_id: 'SAME', types: ['logo'] },
                    { name: 'B', folder_id: 'SAME', types: ['logo'] },
                ]}
            />
        );

        // folder_id is editable and may repeat, so it cannot identify the row.
        fireEvent.click(splitButtons()[1]);

        await waitFor(() => expect(names()).toEqual(['A', 'B Logos']));
    });

    it('still routes the split after its folder id is edited mid-flight', async () => {
        let settle;
        mockPost.mockImplementation(() => new Promise(resolve => (settle = resolve)));
        render(<Harness initial={[{ name: 'A', folder_id: 'OLD', types: ['logo'] }]} />);

        fireEvent.click(splitButtons()[0]);
        await waitFor(() => expect(settle).toBeDefined());
        fireEvent.change(screen.getByLabelText('Drive folder ID'), { target: { value: 'NEW' } });
        settle({ data: { subfolders: SUBFOLDERS } });

        await waitFor(() => expect(names()).toEqual(['A Logos']));
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('reports a failure when the split routes nothing', async () => {
        mockPost.mockResolvedValue({ data: { subfolders: SUBFOLDERS } });
        render(<Harness initial={[{ name: 'A', folder_id: 'X', types: [] }]} />);

        fireEvent.click(splitButtons()[0]);

        // The row claims no types, so it is left untouched — success would be a lie.
        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        expect(toast.success).not.toHaveBeenCalled();
        expect(names()).toEqual(['A']);
    });

    it('aborts an in-flight split when the field unmounts', async () => {
        let signal;
        mockPost.mockImplementation((url, body, options) => {
            signal = options?.signal;
            return new Promise(() => {});
        });
        const { unmount } = render(
            <Harness initial={[{ name: 'A', folder_id: 'X', types: ['logo'] }]} />
        );

        fireEvent.click(splitButtons()[0]);
        await waitFor(() => expect(signal).toBeDefined());
        expect(signal.aborted).toBe(false);

        unmount();
        expect(signal.aborted).toBe(true);
    });

    it('aborts an in-flight upload test when the field unmounts', async () => {
        let signal;
        mockPost.mockImplementation((url, body, options) => {
            signal = options?.signal;
            return new Promise(() => {});
        });
        const { unmount } = render(
            <Harness initial={[{ name: 'A', folder_id: 'X', types: ['logo'] }]} />
        );

        fireEvent.click(screen.getByRole('button', { name: /Test upload/ }));
        await waitFor(() => expect(signal).toBeDefined());

        unmount();
        expect(signal.aborted).toBe(true);
    });

    it('routes two concurrent splits to their own rows', async () => {
        const settle = [];
        mockPost.mockImplementation(() => new Promise(resolve => settle.push(resolve)));
        render(
            <Harness
                initial={[
                    { name: 'A', folder_id: 'A1', types: ['logo', 'background'] },
                    { name: 'B', folder_id: 'B1', types: ['squareart'] },
                ]}
            />
        );

        // Captured before the clicks: a busy button relabels itself to "Splitting…".
        const [splitA, splitB] = splitButtons();
        fireEvent.click(splitA);
        fireEvent.click(splitB);
        await waitFor(() => expect(settle).toHaveLength(2));

        // A expands into two rows, shifting B down; B must still land on B.
        settle[0]({ data: { subfolders: SUBFOLDERS } });
        settle[1]({ data: { subfolders: SUBFOLDERS } });

        await waitFor(() => expect(names()).toEqual(['A Logos', 'A Backgrounds', 'B Square']));
    });

    it('keeps a claimed type the split did not return on the original row', async () => {
        mockPost.mockResolvedValue({ data: { subfolders: SUBFOLDERS } });
        render(<Harness initial={[{ name: 'A', folder_id: 'X', types: ['poster', 'logo'] }]} />);

        fireEvent.click(splitButtons()[0]);

        // The endpoint only ever creates logos/backgrounds/squareart, so a poster
        // claim would otherwise vanish with the parent row it replaced.
        await waitFor(() => expect(names()).toEqual(['A', 'A Logos']));
        expect(screen.getAllByLabelText('Drive folder ID')[0]).toHaveValue('X');
    });

    it('reports a failure when only unroutable types are claimed', async () => {
        mockPost.mockResolvedValue({ data: { subfolders: SUBFOLDERS } });
        render(<Harness initial={[{ name: 'A', folder_id: 'X', types: ['poster'] }]} />);

        fireEvent.click(splitButtons()[0]);

        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        expect(toast.success).not.toHaveBeenCalled();
        expect(names()).toEqual(['A']);
    });
});
