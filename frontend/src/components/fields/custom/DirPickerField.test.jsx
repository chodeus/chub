/** Guards the start directory, the Go up boundary, and the destination write warning. */
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';

const api = vi.hoisted(() => ({
    listed: [],
    roots: [],
    probes: [],
    dirs: {},
    refused: {},
    held: {},
}));

vi.mock('../../../utils/api/system.js', () => ({
    systemAPI: {
        listAllowedRoots: () => Promise.resolve({ data: { roots: api.roots } }),
        listDirectory: async (path, options = {}) => {
            api.listed.push(path);
            api.probes.push(!!options.checkWrite);
            await api.held[path];
            return {
                data: { directories: api.dirs[path] || [], write_error: api.refused[path] ?? null },
            };
        },
        createDirectory: () => Promise.resolve(),
    },
}));

const { DirPickerField } = await import('./DirPickerField.jsx');

const field = { key: 'dir', label: 'Directory' };

describe('DirPickerField', () => {
    beforeEach(() => {
        api.listed.length = 0;
        api.probes.length = 0;
        api.roots = ['/data', '/media'];
        api.dirs = {};
        api.refused = {};
        api.held = {};
    });

    const hold = path => {
        let release;
        api.held[path] = new Promise(resolve => {
            release = resolve;
        });
        return release;
    };

    const REFUSAL =
        'Cannot create files in /kometa: Permission denied (CHUB runs as 1000:100; the folder ' +
        "is owned by 0:0, drwxr-xr-x). Check the volume's host path, and that the folder's " +
        'owner matches PUID/PGID.';
    const destination = { ...field, checkWritable: true };

    it("warns with the server's reason when CHUB cannot write a destination folder", async () => {
        api.roots = ['/kometa'];
        api.refused['/kometa'] = REFUSAL;
        render(<DirPickerField field={destination} value="/kometa" onChange={() => {}} />);

        expect(await screen.findByRole('alert')).toHaveTextContent(REFUSAL);
        expect(api.probes).toEqual([true]);
    });

    it('keeps the warning until the next folder answers, then drops it there', async () => {
        api.roots = ['/kometa'];
        api.dirs['/kometa'] = ['config'];
        api.refused['/kometa'] = REFUSAL;
        const release = hold('/kometa/config');
        render(<DirPickerField field={destination} value="/kometa" onChange={() => {}} />);
        const warning = await screen.findByRole('alert');

        fireEvent.click(screen.getByRole('button', { name: /config$/ }));
        expect(screen.getByRole('alert')).toBe(warning);
        await act(async () => release());

        expect(await screen.findByTitle('/kometa/config')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('ignores a slow folder answer once the user has gone up', async () => {
        api.roots = ['/kometa'];
        api.dirs['/kometa/a'] = ['b'];
        api.refused['/kometa/a/b'] = REFUSAL;
        const release = hold('/kometa/a/b');
        render(<DirPickerField field={destination} value="/kometa/a" onChange={() => {}} />);
        await screen.findByTitle('/kometa/a');

        fireEvent.click(screen.getByRole('button', { name: /b$/ }));
        fireEvent.click(screen.getByRole('button', { name: /\.\.$/ }));
        expect(await screen.findByTitle('/kometa')).toBeInTheDocument();
        await act(async () => release());

        expect(screen.getByTitle('/kometa')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('browses a source folder without asking the server to create a file', async () => {
        render(<DirPickerField field={field} value="/media" onChange={() => {}} />);
        expect(await screen.findByTitle('/media')).toBeInTheDocument();
        expect(api.probes).toEqual([false]);
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
