/** Guards the explicit 0 minimum: the last directory row stays removable. */
import { render as rtlRender, screen } from '@testing-library/react';
import { UIStateProvider } from '../../../contexts/UIStateContext.jsx';

const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

vi.mock('../../../utils/touchDetection', () => ({ useTouchDevice: () => false }));

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
});
