/** Guards the base read from saved drives, saved-location rows, and the Poster Renamerr overlap warning. */
import { render, screen, fireEvent, within } from '@testing-library/react';

const presetsMock = vi.hoisted(() => ({ list: [] }));

vi.mock('../../../utils/gdrivePresets.js', async importOriginal => ({
    ...(await importOriginal()),
    fetchGdrivePresets: () => Promise.resolve(presetsMock.list),
}));
vi.mock('../../../hooks/useInstancesData', () => ({
    useInstancesData: () => ({ instancesData: {} }),
}));
vi.mock('../../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success() {}, error() {} }),
}));

const { BulkPresetPicker } = await import('./BulkPresetPicker.jsx');
const { ArrayObjectField } = await import('./ArrayObjectField.jsx');
const { SETTINGS_SCHEMA } = await import('../../../utils/constants/settings_schema.js');
const { UIStateProvider } = await import('../../../contexts/UIStateContext.jsx');

const PRESETS = [
    { name: 'CL2K Solen', id: 'p-cl2k-solen', style: 'CL2K' },
    { name: 'CL2K Chodeus', id: 'p-cl2k-chodeus', style: 'CL2K' },
    { name: 'MM2K Drazzilb', id: 'p-mm2k-drazzilb', style: 'MM2K' },
    { name: 'Artwork BZ', id: 'p-art-bz', style: 'Artwork' },
];

const field = {
    key: 'gdrive_list',
    bulkPreset: { presetUrl: '/api/gdrive-presets', locationTemplate: '{base}/{style}/{name}' },
};
const drive = (id, location) => ({ name: id, id, location });

const renderPicker = (value, props = {}) => {
    const onChange = vi.fn();
    render(<BulkPresetPicker field={field} value={value} onChange={onChange} {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /Bulk-add from presets/ }));
    return onChange;
};
const baseBox = () => screen.getByLabelText('Global base directory');
const loaded = () => screen.findByRole('checkbox', { name: /^CL2K Solen/ });
const addPreset = async name => {
    fireEvent.click(await screen.findByRole('checkbox', { name: new RegExp(`^${name}`) }));
    fireEvent.click(screen.getByRole('button', { name: /^Add 1 selected drive$/ }));
};

beforeEach(() => {
    presetsMock.list = PRESETS;
});

describe('BulkPresetPicker base directory', () => {
    it('reads the base from drives laid out in style folders', async () => {
        renderPicker([
            drive('a', '/kometa/posters/CL2K/Wenisinmood01'),
            drive('b', '/kometa/posters/MM2K/Solen01'),
            drive('c', '/kometa/posters/Artwork/BZ'),
        ]);
        await loaded();

        expect(baseBox()).toHaveValue('/kometa/posters');
    });

    it('reads the base from a flat DAPS layout with a lowercase style folder', async () => {
        renderPicker([
            drive('a', '/posters/drazzilb'),
            drive('b', '/posters/solens_collection'),
            drive('c', '/posters/cl2k/Solen'),
            drive('d', '/posters/cl2k/MiniMyself/'),
            drive('e', '/posters/cl2k/Iamspartacus'),
        ]);
        await loaded();

        expect(baseBox()).toHaveValue('/posters');
    });

    it('picks the base most drives use', async () => {
        renderPicker([
            drive('a', '/mnt/b/CL2K/x'),
            drive('b', '/mnt/a/CL2K/x'),
            drive('c', '/mnt/a/MM2K/y'),
        ]);
        await loaded();
        expect(baseBox()).toHaveValue('/mnt/a');
    });

    it('takes the first base seen when counts tie', async () => {
        renderPicker([drive('a', '/mnt/b/CL2K/x'), drive('b', '/mnt/a/CL2K/x')]);
        await loaded();
        expect(baseBox()).toHaveValue('/mnt/b');
    });

    it('does not split the vote over a doubled slash', async () => {
        renderPicker([
            drive('a', '/other/CL2K/a'),
            drive('b', '/other/CL2K/b'),
            drive('c', '/posters/CL2K/c'),
            drive('d', '/posters/MM2K/d'),
            drive('e', '/posters//CL2K/e'),
        ]);
        await loaded();
        expect(baseBox()).toHaveValue('/posters');
    });

    it('ignores drives at the filesystem root or on relative paths', async () => {
        renderPicker([
            drive('a', 'posters/x'),
            drive('b', 'posters/y'),
            drive('c', '/CL2K/Solen'),
            drive('d', '/drazzilb'),
            drive('e', '/posters/zarox'),
        ]);
        await loaded();

        expect(baseBox()).toHaveValue('/posters');
    });

    it('leaves the box empty with an example hint when there are no drives', async () => {
        renderPicker([]);
        await loaded();

        expect(baseBox()).toHaveValue('');
        expect(baseBox()).toHaveAttribute('placeholder', 'e.g. /posters');
    });

    it('does not guess a base before the preset styles are known', async () => {
        presetsMock.list = [];
        renderPicker([drive('a', '/kometa/posters/CL2K/Solen')]);

        expect(await screen.findByText('No presets available.')).toBeInTheDocument();
        expect(baseBox()).toHaveValue('');
    });

    it('lets a typed value win, and keeps a cleared box cleared', async () => {
        renderPicker([drive('a', '/kometa/posters/CL2K/Solen')]);
        await loaded();

        fireEvent.change(baseBox(), { target: { value: '/elsewhere' } });
        expect(baseBox()).toHaveValue('/elsewhere');
        fireEvent.change(baseBox(), { target: { value: '' } });
        expect(baseBox()).toHaveValue('');
    });
});

describe('BulkPresetPicker rows and locations', () => {
    it('shows an added drive at its saved location, not a rebuilt preview', async () => {
        renderPicker([
            { name: 'CL2K Solen', id: 'p-cl2k-solen', location: '/kometa/posters/CL2K/Solen01' },
        ]);
        const added = await loaded();
        const chodeus = screen.getByRole('checkbox', { name: /^CL2K Chodeus/ });

        expect(added).toBeDisabled();
        expect(within(added.closest('label')).getByText('(Already added)')).toBeInTheDocument();
        expect(
            within(added.closest('label')).getByText('/kometa/posters/CL2K/Solen01')
        ).toBeInTheDocument();
        expect(
            within(chodeus.closest('label')).getByText('/kometa/posters/CL2K/Chodeus')
        ).toBeInTheDocument();
    });

    it('adds new drives under the base read from saved drives', async () => {
        const onChange = renderPicker([drive('a', '/posters/drazzilb')]);
        await addPreset('MM2K Drazzilb');

        expect(onChange).toHaveBeenCalledWith([
            drive('a', '/posters/drazzilb'),
            { name: 'MM2K Drazzilb', id: 'p-mm2k-drazzilb', location: '/posters/MM2K/Drazzilb' },
        ]);
    });

    it('keeps the leading slash for a "/" base', async () => {
        const onChange = renderPicker([]);
        await loaded();
        fireEvent.change(baseBox(), { target: { value: '/' } });
        await addPreset('CL2K Solen');

        expect(onChange.mock.calls[0][0][0].location).toBe('/CL2K/Solen');
    });

    it('trims spaces around a typed base', async () => {
        const onChange = renderPicker([]);
        await loaded();
        fireEvent.change(baseBox(), { target: { value: '  /posters/  ' } });
        await addPreset('CL2K Solen');

        expect(onChange.mock.calls[0][0][0].location).toBe('/posters/CL2K/Solen');
    });

    it.each([
        ['../posters', '../posters/CL2K/Solen'],
        ['../../a/../posters', '../../posters/CL2K/Solen'],
        ['/../posters', '/posters/CL2K/Solen'],
    ])('keeps leading ".." only on a relative base (%s)', async (base, location) => {
        const onChange = renderPicker([]);
        await loaded();
        fireEvent.change(baseBox(), { target: { value: base } });
        await addPreset('CL2K Solen');

        expect(onChange.mock.calls[0][0][0].location).toBe(location);
    });

    it('puts new drives in the style folder already used under the base', async () => {
        const onChange = renderPicker([drive('a', '/posters/cl2k/Solen')]);
        const chodeus = await screen.findByRole('checkbox', { name: /^CL2K Chodeus/ });

        expect(
            within(chodeus.closest('label')).getByText('/posters/cl2k/Chodeus')
        ).toBeInTheDocument();
        await addPreset('CL2K Chodeus');
        expect(onChange.mock.calls[0][0][1].location).toBe('/posters/cl2k/Chodeus');
    });

    it('uses the preset spelling under a base with no saved style folder', async () => {
        const onChange = renderPicker([drive('a', '/posters/cl2k/Solen')]);
        await loaded();
        fireEvent.change(baseBox(), { target: { value: '/new' } });
        await addPreset('CL2K Chodeus');

        expect(onChange.mock.calls[0][0][1].location).toBe('/new/CL2K/Chodeus');
    });

    it('reuses the saved style folder under a relative "." base too', async () => {
        const onChange = renderPicker([drive('a', 'cl2k/Solen')]);
        await loaded();
        fireEvent.change(baseBox(), { target: { value: '.' } });
        await addPreset('CL2K Chodeus');

        expect(onChange.mock.calls[0][0][1].location).toBe('cl2k/Chodeus');
    });
});

describe('BulkPresetPicker shared folders', () => {
    it('blocks a re-shared preset whose folder a saved drive already syncs into', async () => {
        renderPicker([
            { name: 'Solen (old share)', id: 'old-id', location: '/posters/cl2k/Solen' },
        ]);
        const row = await loaded();

        expect(row).toBeDisabled();
        expect(
            within(row.closest('label')).getByText('(folder in use by Solen (old share))')
        ).toBeInTheDocument();
    });

    it('matches the folder regardless of case', async () => {
        renderPicker([{ name: 'Old', id: 'old-id', location: '/posters/CL2K/solen' }]);
        expect(await loaded()).toBeDisabled();
    });

    it('never adds two presets of one batch to the same folder', async () => {
        presetsMock.list = [
            { name: 'CL2K Solen', id: 'solen-a', style: 'CL2K' },
            { name: 'CL2K Solen', id: 'solen-b', style: 'CL2K' },
        ];
        const onChange = renderPicker([drive('x', '/posters/CL2K/Other')]);
        const boxes = await screen.findAllByRole('checkbox', { name: /^CL2K Solen/ });
        boxes.forEach(b => fireEvent.click(b));
        fireEvent.click(screen.getByRole('button', { name: /^Add 2 selected drives$/ }));

        const added = onChange.mock.calls[0][0].slice(1);
        expect(added.map(e => e.location)).toEqual(['/posters/CL2K/Solen']);
    });
});

describe('BulkPresetPicker Poster Renamerr overlap', () => {
    const warning = () => screen.queryByText(/Poster Renamerr's destination directory/);
    const withDestination = (destination_dir, apply_method) => ({
        rootConfig: { poster_renamerr: { destination_dir, apply_method } },
    });

    it.each([
        ['/kometa', '/kometa/posters'],
        ['/kometa/', '/kometa'],
        ['/', '/posters'],
        ['/kometa', '/other/../kometa/posters'],
    ])('warns when destination %s holds base %s', async (destination, base) => {
        renderPicker([], withDestination(destination));
        await loaded();
        fireEvent.change(baseBox(), { target: { value: base } });

        expect(warning()).toBeInTheDocument();
        expect(baseBox()).toHaveAttribute(
            'aria-describedby',
            'bulk_base_dir-desc bulk_base_dir-warn'
        );
    });

    it.each([
        ['/kometa/assets', '/kometa/posters'],
        ['/kometa/assets', '/kometa/assets2'],
        ['', '/kometa'],
        ['/kometa', '/kometa/../other'],
    ])('stays quiet when destination %s does not hold base %s', async (destination, base) => {
        renderPicker([], withDestination(destination));
        await loaded();
        fireEvent.change(baseBox(), { target: { value: base } });

        expect(warning()).not.toBeInTheDocument();
    });

    it.each([
        ['kometa', true],
        ['plex', false],
    ])('with apply_method %s, warns: %s', async (method, warns) => {
        renderPicker(
            [drive('a', '/kometa/posters/CL2K/Solen')],
            withDestination('/kometa', method)
        );
        await loaded();

        expect(!!warning()).toBe(warns);
    });

    it('stays quiet without a root config', async () => {
        renderPicker([drive('a', '/kometa/posters/CL2K/Solen')]);
        await loaded();
        expect(warning()).not.toBeInTheDocument();
    });
});

describe('Sync GDrive field wiring', () => {
    const gdriveField = SETTINGS_SCHEMA.find(m => m.key === 'sync_gdrive').fields.find(
        f => f.key === 'gdrive_list'
    );

    it.each([true, false])(
        'fills the base and warns (alwaysExpanded: %s)',
        async alwaysExpanded => {
            render(
                <UIStateProvider>
                    <ArrayObjectField
                        field={{ ...gdriveField, id: 'gdrive_list', alwaysExpanded }}
                        value={[drive('a', '/kometa/posters/CL2K/Solen')]}
                        onChange={() => {}}
                        rootConfig={{ poster_renamerr: { destination_dir: '/kometa' } }}
                    />
                </UIStateProvider>
            );
            fireEvent.click(screen.getByRole('button', { name: /Bulk-add from presets/ }));
            await loaded();

            expect(baseBox()).toHaveValue('/kometa/posters');
            expect(
                screen.getByText(
                    /Poster Renamerr's destination directory \(\/kometa\) or a folder inside it/
                )
            ).toBeInTheDocument();
        }
    );
});
