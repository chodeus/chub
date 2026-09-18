/** Guards the local draft: text stays on screen; blur clamps finite drafts and drops "-". */
import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { FloatField } from './FloatField.jsx';

function Harness({ onChange, field }) {
    const [value, setValue] = useState(0.5);
    return (
        <FloatField
            field={{ key: 'threshold', label: 'Threshold', ...field }}
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
        expect(onChange).not.toHaveBeenCalled();
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

    it('lets the "5" of "50" through with min 10 and clamps out-of-range text on blur', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} field={{ min: 10 }} />);
        const input = screen.getByLabelText('Threshold');

        fireEvent.change(input, { target: { value: '5' } });
        expect(input).toHaveValue('5');
        expect(onChange).not.toHaveBeenCalled();
        fireEvent.change(input, { target: { value: '50' } });
        expect(onChange).toHaveBeenLastCalledWith(0.5);

        fireEvent.change(input, { target: { value: '500' } });
        expect(onChange).toHaveBeenLastCalledWith(0.5);
        fireEvent.blur(input);
        expect(onChange).toHaveBeenLastCalledWith(1);
    });

    it('clamps a stepper click to the configured minimum', () => {
        const onChange = vi.fn();
        render(
            <FloatField
                field={{ key: 'threshold', label: 'Threshold', min: 10 }}
                value={null}
                onChange={onChange}
            />
        );

        fireEvent.click(screen.getByRole('button', { name: 'Increase Threshold' }));

        expect(onChange).toHaveBeenCalledWith(0.1);
    });
});
