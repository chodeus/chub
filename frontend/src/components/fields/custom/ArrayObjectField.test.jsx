/** Guards the open editor against a removal above it, and the row's button semantics. */
import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../../../hooks/useInstancesData', () => ({
    useInstancesData: () => ({ instancesData: {} }),
}));
vi.mock('../../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success() {}, error() {} }),
}));

const { ArrayObjectField } = await import('./ArrayObjectField.jsx');

const field = {
    key: 'items',
    label: 'Items',
    type: 'object_array',
    fields: [{ key: 'name', type: 'text', label: 'Name' }],
};
const rows = ['Alpha', 'Bravo', 'Charlie', 'Delta'].map(name => ({ name }));

function Harness({ onChange }) {
    const [value, setValue] = useState(rows);
    return (
        <ArrayObjectField
            field={field}
            value={value}
            onChange={next => {
                setValue(next);
                onChange(next);
            }}
        />
    );
}

const openRow = name =>
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}`) }));
const rename = text => fireEvent.change(screen.getByLabelText('Name'), { target: { value: text } });
const removeFirstRow = () =>
    fireEvent.click(screen.getByRole('button', { name: 'Remove Drive Location 1' }));
const lastSaved = onChange => onChange.mock.calls.at(-1)[0].map(row => row.name);

describe('ArrayObjectField', () => {
    it('saves the open draft to its own row after a row above is removed', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);

        openRow('Charlie');
        rename('Charlie 2');
        removeFirstRow();
        fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

        expect(lastSaved(onChange)).toEqual(['Bravo', 'Charlie 2', 'Delta']);
    });

    it('does not duplicate the last row when a row above it is removed', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);

        openRow('Delta');
        rename('Delta 2');
        removeFirstRow();
        fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

        expect(lastSaved(onChange)).toEqual(['Bravo', 'Charlie', 'Delta 2']);
    });

    it('exposes each row summary as a button that reports its expanded state', () => {
        render(<Harness onChange={() => {}} />);
        const row = screen.getByRole('button', { name: /^Bravo/ });

        expect(row).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(row);
        expect(row).toHaveAttribute('aria-expanded', 'true');
        expect(row).not.toContainElement(
            screen.getByRole('button', { name: 'Remove Drive Location 2' })
        );
    });

    it('opens a row whose schema has no fields array', () => {
        render(
            <ArrayObjectField
                field={{ key: 'items', label: 'Items' }}
                value={[{ name: 'Alpha' }]}
                onChange={() => {}}
            />
        );
        openRow('Alpha');
        expect(screen.getByRole('button', { name: 'Save Changes' })).toBeInTheDocument();
    });

    it('renders always-expanded cards whose schema has no fields array', () => {
        render(
            <ArrayObjectField
                field={{ key: 'items', label: 'Items', alwaysExpanded: true }}
                value={[{ name: 'Alpha' }]}
                onChange={() => {}}
            />
        );
        expect(screen.getByText('Alpha')).toBeInTheDocument();
    });
});
