/** Guards the start directory when the saved value sits under no allowed root. */
import { render, waitFor } from '@testing-library/react';

const listed = vi.hoisted(() => []);

vi.mock('../../../utils/api/system.js', () => ({
    systemAPI: {
        listAllowedRoots: () => Promise.resolve({ data: { roots: ['/data', '/media'] } }),
        listDirectory: path => {
            listed.push(path);
            return Promise.resolve({ data: { directories: [] } });
        },
        createDirectory: () => Promise.resolve(),
    },
}));

const { DirPickerField } = await import('./DirPickerField.jsx');

const field = { key: 'dir', label: 'Directory' };

describe('DirPickerField', () => {
    beforeEach(() => {
        listed.length = 0;
    });

    it('opens the first root when the saved path is under no allowed root', async () => {
        render(<DirPickerField field={field} value="/elsewhere/posters" onChange={() => {}} />);
        await waitFor(() => expect(listed).toEqual(['/data']));
    });

    it('opens the saved path when an allowed root contains it', async () => {
        render(<DirPickerField field={field} value="/media/movies" onChange={() => {}} />);
        await waitFor(() => expect(listed).toEqual(['/media/movies']));
    });
});
