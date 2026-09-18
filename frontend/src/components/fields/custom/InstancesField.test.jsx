/** Guards orphaned Plex entries, the help tooltip, and single-control checkbox rows. */
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success() {}, error() {} }),
}));
vi.mock('../../../utils/api', () => ({
    instancesAPI: {
        fetchInstances: () =>
            Promise.resolve({
                radarr: { radarr_1: { url: 'http://radarr' } },
                plex: { plex_1: { url: 'http://plex' } },
            }),
        fetchPlexLibraries: () =>
            Promise.resolve({ data: { libraries: [{ title: 'Movies', type: 'movie' }] } }),
        fetchPlexCatalog: () =>
            Promise.resolve({
                data: { libraries: { plex_1: [{ title: 'Movies', type: 'movie' }] } },
            }),
    },
}));

const { InstancesField } = await import('./InstancesField.jsx');

const posterField = {
    key: 'instances',
    label: 'Instances',
    type: 'instances',
    instance_types: ['radarr', 'plex'],
    add_posters_option: true,
};

describe('InstancesField', () => {
    it('keeps an orphaned object-shaped Plex entry when another instance is toggled', async () => {
        const orphan = { plex_old: { library_names: ['Movies'], add_posters: true } };
        const onChange = vi.fn();
        render(<InstancesField field={posterField} value={[orphan]} onChange={onChange} />);

        fireEvent.click(await screen.findByRole('button', { name: /radarr/i }));
        expect(onChange).toHaveBeenCalledWith(['radarr_1', orphan]);
    });

    it('keeps the help tooltip once instances have loaded', async () => {
        render(
            <InstancesField
                field={{ ...posterField, helpText: 'Pick the servers to use' }}
                value={[]}
                onChange={() => {}}
            />
        );
        await screen.findByRole('button', { name: /radarr/i });
        expect(screen.getByRole('button', { name: 'More info' })).toBeInTheDocument();
    });

    it('makes the checkbox the only control on Plex instance, upload and library rows', async () => {
        const onChange = vi.fn();
        const { container } = render(
            <InstancesField
                field={posterField}
                value={[{ plex_1: { library_names: [], add_posters: false } }]}
                onChange={onChange}
            />
        );
        await screen.findByRole('checkbox', { name: 'Movies' });

        expect(container.querySelectorAll('div[role="button"], div[tabindex]')).toHaveLength(0);
        fireEvent.click(screen.getByText('Upload to this Plex instance'));
        expect(onChange).toHaveBeenCalledTimes(1);
    });

    it('makes the checkbox the only control on plex_scope rows', async () => {
        const { container } = render(
            <InstancesField
                field={{ key: 'plex', label: 'Plex', type: 'plex_scope' }}
                value={[{ instance: 'plex_1', library_names: [] }]}
                onChange={() => {}}
            />
        );
        await screen.findByRole('checkbox', { name: 'Movies' });
        expect(container.querySelectorAll('div[role="button"], div[tabindex]')).toHaveLength(0);
    });
});
