/** Guards the stale-result key: rows whose values join to the same text must not share a result. */
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../../../utils/api/core', async importOriginal => ({
    ...(await importOriginal()),
    apiCore: { post: () => Promise.resolve({ message: 'Folder reachable' }) },
}));
vi.mock('../../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success() {}, error() {} }),
}));

const { ActionButtonField } = await import('./ActionButtonField.jsx');

const field = { key: 'test', endpoint: '/gdrive/test', payloadFields: ['a', 'b'] };

describe('ActionButtonField', () => {
    it('drops the result when the row changes, even if the joined values collide', async () => {
        const { rerender } = render(
            <ActionButtonField field={field} rowData={{ a: 'x y', b: 'z' }} />
        );
        fireEvent.click(screen.getByRole('button', { name: 'Test' }));
        expect(await screen.findByText('Folder reachable')).toBeInTheDocument();

        rerender(<ActionButtonField field={field} rowData={{ a: 'x', b: 'y z' }} />);
        expect(screen.queryByText('Folder reachable')).not.toBeInTheDocument();
    });
});
