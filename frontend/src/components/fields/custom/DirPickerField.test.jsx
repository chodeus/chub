/** Guards the start directory: the saved path under a matching root, else the first root. */
import { render, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({ listed: [], roots: [] }));

vi.mock('../../../utils/api/system.js', () => ({
    systemAPI: {
        listAllowedRoots: () => Promise.resolve({ data: { roots: api.roots } }),
        listDirectory: path => {
            api.listed.push(path);
            return Promise.resolve({ data: { directories: [] } });
        },
        createDirectory: () => Promise.resolve(),
    },
}));

const { DirPickerField } = await import('./DirPickerField.jsx');

const field = { key: 'dir', label: 'Directory' };

describe('DirPickerField', () => {
    beforeEach(() => {
        api.listed.length = 0;
        api.roots = ['/data', '/media'];
    });

    it('opens the first root when the saved path is under no allowed root', async () => {
        render(<DirPickerField field={field} value="/elsewhere/posters" onChange={() => {}} />);
        await waitFor(() => expect(api.listed).toEqual(['/data']));
    });

    it('opens the saved path when an allowed root contains it', async () => {
        render(<DirPickerField field={field} value="/media/movies" onChange={() => {}} />);
        await waitFor(() => expect(api.listed).toEqual(['/media/movies']));
    });

    it.each(['/', '/media/'])('opens the saved path under a root of %s', async root => {
        api.roots = [root];
        render(<DirPickerField field={field} value="/media/movies" onChange={() => {}} />);
        await waitFor(() => expect(api.listed).toEqual(['/media/movies']));
    });
});
