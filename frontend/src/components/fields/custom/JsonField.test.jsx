/** Guards the JSON status line: it must describe the text on screen, not the last edit. */
import { render, screen, fireEvent } from '@testing-library/react';
import { JsonField } from './JsonField.jsx';

const field = { key: 'extra', label: 'Extra' };

describe('JsonField', () => {
    it('flags invalid JSON supplied as the initial value', () => {
        render(<JsonField field={field} value="{bad" onChange={() => {}} />);

        expect(screen.queryByText('Valid JSON')).not.toBeInTheDocument();
        expect(screen.getAllByText(/Invalid JSON/).length).toBeGreaterThan(0);
    });

    it('tracks the text as the user edits it', () => {
        const onChange = vi.fn();
        render(<JsonField field={field} value='{"a": 1}' onChange={onChange} />);
        expect(screen.getByText('Valid JSON')).toBeInTheDocument();

        fireEvent.change(screen.getByLabelText('Extra'), { target: { value: '{"a":' } });
        expect(screen.queryByText('Valid JSON')).not.toBeInTheDocument();
        expect(onChange).toHaveBeenLastCalledWith('{"a":');
    });
});
