/** Guards that a stored 0 is shown rather than blanked. */
import { render, screen } from '@testing-library/react';
import { TextareaField } from './TextareaField.jsx';

describe('TextareaField', () => {
    it('shows a stored 0', () => {
        render(
            <TextareaField field={{ key: 'notes', label: 'Notes' }} value={0} onChange={() => {}} />
        );
        expect(screen.getByLabelText('Notes')).toHaveValue('0');
    });
});
