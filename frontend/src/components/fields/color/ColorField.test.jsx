/** Guards the color pair's group name, and that the field description reaches the hex input. */
import { render, screen } from '@testing-library/react';
import { ColorField } from './ColorField.jsx';

const field = { key: 'border', label: 'Border Color', description: 'Hex only' };

describe('ColorField', () => {
    it('names the picker and text input group by the field label', () => {
        render(<ColorField field={field} value="#ff0000" onChange={() => {}} />);
        expect(screen.getByRole('group', { name: 'Border Color' })).toBeInTheDocument();
    });

    it('describes the hex input by the field description', () => {
        render(<ColorField field={field} value="#ff0000" onChange={() => {}} />);
        expect(
            screen.getByRole('textbox', { name: 'Hex color input for Border Color' })
        ).toHaveAccessibleDescription('Hex only');
    });
});
