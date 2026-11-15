/** Guards the explicit 0 minimum, and the write check on folders CHUB writes into. */
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react';
import { UIStateProvider } from '../../../contexts/UIStateContext.jsx';
import { SETTINGS_SCHEMA } from '../../../utils/constants/settings_schema.js';

const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

vi.mock('../../../utils/touchDetection', () => ({ useTouchDevice: () => false }));
const probes = vi.hoisted(() => []);
vi.mock('../../../utils/api/system.js', () => ({
    systemAPI: {
        listAllowedRoots: () => Promise.resolve({ data: { roots: ['/media'] } }),
        listDirectory: (path, options = {}) => {
            probes.push([path, !!options.checkWrite]);
            return Promise.resolve({ data: { directories: [] } });
        },
        createDirectory: () => Promise.resolve(),
    },
}));

const { DirListField } = await import('./DirListField.jsx');

describe('DirListField', () => {
    it('lets an explicit min_directories of 0 remove the last row', () => {
        render(
            <DirListField
                field={{ key: 'dirs', label: 'Dirs', min_directories: 0 }}
                value={['/a']}
                onChange={() => {}}
            />
        );
        expect(screen.getByRole('button', { name: 'Remove dirs 1' })).toBeEnabled();
    });

    it('keeps the last row when no minimum is set', () => {
        render(
            <DirListField
                field={{ key: 'dirs', label: 'Dirs' }}
                value={['/a']}
                onChange={() => {}}
            />
        );
        expect(screen.getByRole('button', { name: 'Remove dirs 1' })).toBeDisabled();
    });

    const jduparrDirs = SETTINGS_SCHEMA.find(m => m.key === 'jduparr').fields.find(
        f => f.key === 'source_dirs'
    );
    it.each([
        ["jduparr's hardlink folders", true, jduparrDirs],
        ['a folder list without the flag', false, { key: 'dirs', label: 'Dirs' }],
    ])('browses %s with write check %s', async (_name, checked, dirs) => {
        probes.length = 0;
        render(<DirListField field={dirs} value={['/media']} onChange={() => {}} />);

        fireEvent.click(screen.getByRole('button', { name: /^Browse for .* 1$/ }));

        await waitFor(() => expect(probes).toEqual([['/media', checked]]));
    });
});
