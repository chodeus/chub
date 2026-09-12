/** Guards 0-valued dropdown options, no hidden primary source, and stored date ranges. */
import { render, screen } from '@testing-library/react';
import { DropdownField } from './DropdownField.jsx';
import { PrimarySourceField } from './PrimarySourceField.jsx';
import { DateRangeField } from './DateRangeField.jsx';

describe('DropdownField', () => {
    it('selects a stored value of 0', () => {
        render(
            <DropdownField
                field={{
                    key: 'level',
                    label: 'Level',
                    options: [
                        { value: 0, label: 'Off' },
                        { value: 1, label: 'On' },
                    ],
                }}
                value={0}
                onChange={() => {}}
            />
        );
        expect(screen.getByLabelText('Level')).toHaveValue('0');
    });
});

describe('PrimarySourceField', () => {
    it('shows no primary until one is stored', () => {
        render(
            <PrimarySourceField
                field={{ key: 'sources', label: 'Primary Source', options: ['local', 'tmdb'] }}
                value={[]}
                onChange={() => {}}
            />
        );
        expect(screen.getByLabelText('Primary Source')).toHaveValue('');
    });
});

describe('DateRangeField', () => {
    const field = { key: 'schedule', label: 'Dates' };

    it('does not overwrite a malformed stored value', () => {
        const onChange = vi.fn();
        render(<DateRangeField field={field} value="garbage" onChange={onChange} />);
        expect(onChange).not.toHaveBeenCalled();
    });

    it('still seeds an unset value with the default range', () => {
        const onChange = vi.fn();
        render(<DateRangeField field={field} value={undefined} onChange={onChange} />);
        expect(onChange).toHaveBeenCalledWith('range(01/01-01/01)');
    });

    it('does not parse a range followed by trailing text', () => {
        render(<DateRangeField field={field} value="range(03/05-04/10)junk" onChange={() => {}} />);
        expect(screen.getByLabelText('From month selection')).toHaveValue('01');
    });
});
