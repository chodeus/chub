/** The folders CHUB writes open a picker that checks CHUB can write there. */
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

const writeChecked = SETTINGS_SCHEMA.flatMap(module =>
    (module.fields || []).flatMap(f => [
        ...(f.checkWritable ? [`${module.key}.${f.key}`] : []),
        ...(f.fields || [])
            .filter(sub => sub.checkWritable)
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

    it('write-checks exactly the module destinations and the GDrive sync location', () => {
        expect(writeChecked).toEqual([
            'sync_gdrive.gdrive_list.location',
            'poster_renamerr.destination_dir',
            'asset_renamerr.destination_dir',
            'border_replacerr.destination_dir',
        ]);
    });

    it("opens poster renamerr's destination picker with the write check", async () => {
        render(<DirField field={posterDestination} value="/kometa" onChange={() => {}} />);

        fireEvent.click(screen.getByRole('textbox'));

        await waitFor(() => expect(api.probes).toEqual([['/kometa', true]]));
    });
});
