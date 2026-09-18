/** Guards that an option whose value is 0 can be the selected one. */
import { render, screen } from '@testing-library/react';
import { SelectBase } from './SelectBase.jsx';

describe('SelectBase', () => {
    it('selects an option whose value is 0', () => {
        render(
            <SelectBase
                id="level"
                value={0}
                onChange={() => {}}
                placeholder="Pick one"
                options={[
                    { value: 0, label: 'Off' },
                    { value: 1, label: 'On' },
                ]}
            />
        );
        expect(screen.getByRole('combobox')).toHaveValue('0');
    });
});
