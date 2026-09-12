/** Guards that a stored 0 is shown rather than blanked, and that the field runs on its own props. */
import { render, screen, fireEvent } from '@testing-library/react';
import { TextField } from './TextField.jsx';

const field = { key: 'port', label: 'Port' };

describe('TextField', () => {
    it('shows a stored 0', () => {
        render(<TextField field={field} value={0} onChange={() => {}} />);
        expect(screen.getByLabelText('Port')).toHaveValue('0');
    });

    it('reports edits through its onChange prop', () => {
        const onChange = vi.fn();
        render(<TextField field={field} value="" onChange={onChange} />);

        fireEvent.change(screen.getByLabelText('Port'), { target: { value: '8080' } });
        expect(onChange).toHaveBeenCalledWith('8080');
    });
});
