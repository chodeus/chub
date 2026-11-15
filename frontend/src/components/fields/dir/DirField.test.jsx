/** The folders CHUB writes into open a picker that checks CHUB can write there. */
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react';
import { UIStateProvider } from '../../../contexts/UIStateContext.jsx';

const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

const api = vi.hoisted(() => ({ probes: [] }));

vi.mock('../../../utils/api/system.js', () => ({
    systemAPI: {
        listAllowedRoots: () => Promise.resolve({ data: { roots: ['/kometa'] } }),
        listDirectory: (path, options = {}) => {
            api.probes.push([path, !!options.checkWrite]);
            return Promise.resolve({ data: { directories: [] } });
        },
        createDirectory: () => Promise.resolve(),
    },
}));

const { DirField } = await import('./DirField.jsx');
const { SETTINGS_SCHEMA } = await import('../../../utils/constants/settings_schema.js');

const writeChecked = when =>
    SETTINGS_SCHEMA.flatMap(module =>
        (module.fields || []).flatMap(f => [
            ...(when(f.checkWritable) ? [`${module.key}.${f.key}`] : []),
            ...(f.fields || [])
                .filter(sub => when(sub.checkWritable))
                .map(sub => `${module.key}.${f.key}.${sub.key}`),
        ])
    );
const posterDestination = SETTINGS_SCHEMA.find(m => m.key === 'poster_renamerr').fields.find(
    f => f.key === 'destination_dir'
);

describe('DirField', () => {
    beforeEach(() => {
        api.probes.length = 0;
    });

    it('always write-checks the destinations, GDrive locations, hardlink and cleanup folders only', () => {
        expect(writeChecked(check => check === true)).toEqual([
            'sync_gdrive.gdrive_list.location',
            'poster_renamerr.destination_dir',
            'asset_renamerr.destination_dir',
            'border_replacerr.destination_dir',
            'jduparr.source_dirs',
            'poster_cleanarr.asset_dirs',
        ]);
    });

    it('write-checks only the poster, music art and asset source folders on some settings', () => {
        expect(writeChecked(Array.isArray)).toEqual([
            'poster_renamerr.source_dirs',
            'poster_renamerr.music_source_dirs',
            'asset_renamerr.source_dirs',
        ]);
    });

    it("opens poster renamerr's destination picker with the write check", async () => {
        render(<DirField field={posterDestination} value="/kometa" onChange={() => {}} />);

        fireEvent.click(screen.getByRole('textbox'));

        await waitFor(() => expect(api.probes).toEqual([['/kometa', true]]));
    });
});
