/** Guards the start directory (saved path under a matching root, else the first root) and the Go up boundary. */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

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

    it('treats a saved path with a trailing slash as the root itself, so Go up stays hidden', async () => {
        api.roots = ['/media'];
        render(<DirPickerField field={field} value="/media/" onChange={() => {}} />);

        expect(await screen.findByTitle('/media')).toBeInTheDocument();
        expect(api.listed).toEqual(['/media']);
        expect(screen.queryByText('..')).toBeNull();
    });

    it('keeps breadcrumb paths canonical when the root is /', async () => {
        api.roots = ['/'];
        render(<DirPickerField field={field} value="/media/movies" onChange={() => {}} />);
        expect(await screen.findByTitle('/media/movies')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'media' }));

        expect(api.listed).toEqual(['/media/movies', '/media']);
    });

    it('treats a trailing-slash root as the root itself, so Go up stays hidden', async () => {
        api.roots = ['/media/'];
        render(<DirPickerField field={field} value="/media" onChange={() => {}} />);

        expect(await screen.findByTitle('/media')).toBeInTheDocument();
        expect(api.listed).toEqual(['/media']);
        expect(screen.queryByText('..')).toBeNull();
    });
});
