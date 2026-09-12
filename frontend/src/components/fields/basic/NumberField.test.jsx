/** Guards bounds: an out-of-range prefix can be typed, blur clamps, and blur still reaches the caller. */
import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { NumberField } from './NumberField.jsx';

function Harness({ onChange, onBlur }) {
    const [value, setValue] = useState(20);
    return (
        <NumberField
            field={{ key: 'count', label: 'Count', min: 10, max: 100 }}
            value={value}
            onChange={next => {
                setValue(next);
                onChange(next);
            }}
            onBlur={onBlur}
        />
    );
}

describe('NumberField', () => {
    it('accepts a keystroke below min on the way to a valid value', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        const input = screen.getByLabelText('Count');

        fireEvent.change(input, { target: { value: '5' } });
        expect(input).toHaveValue('5');
        fireEvent.change(input, { target: { value: '50' } });
        expect(onChange).toHaveBeenLastCalledWith(50);
    });

    it('clamps an out-of-range value on blur and still calls onBlur', () => {
        const onChange = vi.fn();
        const onBlur = vi.fn();
        render(<Harness onChange={onChange} onBlur={onBlur} />);
        const input = screen.getByLabelText('Count');

        fireEvent.change(input, { target: { value: '500' } });
        fireEvent.blur(input);

        expect(onChange).toHaveBeenLastCalledWith(100);
        expect(onBlur).toHaveBeenCalledTimes(1);
    });

    it('keeps a partial "1." on screen and emits only complete numbers', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        const input = screen.getByLabelText('Count');

        fireEvent.change(input, { target: { value: '12.' } });
        expect(input).toHaveValue('12.');
        fireEvent.change(input, { target: { value: '12.5' } });
        expect(input).toHaveValue('12.5');
        expect(onChange).toHaveBeenLastCalledWith(12.5);

        fireEvent.change(input, { target: { value: '-' } });
        expect(onChange.mock.calls.flat().every(v => typeof v === 'number')).toBe(true);
    });

    it('never emits an out-of-range value, so a save without blur sends the last valid one', () => {
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        const input = screen.getByLabelText('Count');

        fireEvent.change(input, { target: { value: '50' } });
        expect(onChange).toHaveBeenLastCalledWith(50);
        fireEvent.change(input, { target: { value: '500' } });
        expect(input).toHaveValue('500');
        expect(onChange).toHaveBeenLastCalledWith(50);
    });
});
