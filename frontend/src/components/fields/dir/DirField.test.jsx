/** The module destination folders open a picker that checks CHUB can write there. */
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

const destinations = SETTINGS_SCHEMA.flatMap(module =>
    (module.fields || []).filter(f => f.key === 'destination_dir').map(f => [module.key, f])
);

describe('DirField', () => {
    beforeEach(() => {
        api.probes.length = 0;
    });

    it('marks the destination folder of every module that writes one', () => {
        expect(destinations.map(([key, f]) => [key, f.checkWritable])).toEqual([
            ['poster_renamerr', true],
            ['asset_renamerr', true],
            ['border_replacerr', true],
        ]);
    });

    it("opens poster renamerr's destination picker with the write check", async () => {
        const [, posterDestination] = destinations[0];
        render(<DirField field={posterDestination} value="/kometa" onChange={() => {}} />);

        fireEvent.click(screen.getByRole('textbox'));

        await waitFor(() => expect(api.probes).toEqual([['/kometa', true]]));
    });
});
