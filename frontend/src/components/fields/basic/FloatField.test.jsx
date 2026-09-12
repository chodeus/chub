/** Guards the local draft: partial input stays on screen and only complete numbers are emitted. */
import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { FloatField } from './FloatField.jsx';

function Harness({ onChange }) {
    const [value, setValue] = useState(0.5);
    return (
        <FloatField
            field={{ key: 'threshold', label: 'Threshold' }}
            value={value}
            onChange={next => {
                setValue(next);
                onChange(next);
            }}
        />
    );
}

describe('FloatField', () => {
    it('keeps "1." on screen and emits 1.5% once the number is complete', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        const input = screen.getByLabelText('Threshold');

        fireEvent.change(input, { target: { value: '1.' } });
        expect(input).toHaveValue('1.');
        fireEvent.change(input, { target: { value: '1.5' } });
        expect(input).toHaveValue('1.5');
        expect(onChange).toHaveBeenLastCalledWith(0.015);
    });

    it('never emits a partial "-", so the steppers stay numeric', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);

        fireEvent.change(screen.getByLabelText('Threshold'), { target: { value: '-' } });
        fireEvent.click(screen.getByRole('button', { name: 'Increase Threshold' }));

        expect(onChange.mock.calls.flat().every(v => v === null || Number.isFinite(v))).toBe(true);
        expect(onChange).toHaveBeenLastCalledWith(0.51);
    });
});
