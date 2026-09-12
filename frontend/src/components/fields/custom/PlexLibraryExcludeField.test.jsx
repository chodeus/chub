/** Guards the library rows: the checkbox and its label are the only control. */
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success() {}, error() {} }),
}));
vi.mock('../../../utils/api', () => ({
    instancesAPI: {
        fetchPlexCatalog: () =>
            Promise.resolve({
                data: { libraries: { plex_1: [{ title: 'Movies' }, { title: 'Shows' }] } },
            }),
    },
}));

const { PlexLibraryExcludeField } = await import('./PlexLibraryExcludeField.jsx');

describe('PlexLibraryExcludeField', () => {
    it('makes the checkbox the only control on each library row', async () => {
        const onChange = vi.fn();
        const { container } = render(
            <PlexLibraryExcludeField
                field={{ key: 'excluded_libraries', label: 'Exclude Libraries' }}
                value={[]}
                onChange={onChange}
            />
        );
        await screen.findByRole('checkbox', { name: 'Movies' });

        expect(container.querySelectorAll('[role="button"], [tabindex]')).toHaveLength(0);
        fireEvent.click(screen.getByText('Shows'));
        expect(onChange).toHaveBeenCalledTimes(1);
        expect(onChange).toHaveBeenCalledWith(['Shows']);
    });
});
