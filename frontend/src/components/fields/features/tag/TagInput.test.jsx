/** Guards per-instance ids, array suggestions, and that TagInputField's label and ARIA reach the input. */
import { render, screen, fireEvent } from '@testing-library/react';
import { TagInput } from './TagInput.jsx';
import { TagInputField } from '../../custom/TagInputField.jsx';

describe('TagInput', () => {
    it('gives each instance its own listbox and description ids', () => {
        render(
            <>
                <TagInput items={[]} suggestions={['logo']} />
                <TagInput items={[]} suggestions={['logo']} />
            </>
        );
        const inputs = screen.getAllByRole('combobox');
        inputs.forEach(input => fireEvent.focus(input));

        const controls = inputs.map(input => input.getAttribute('aria-controls'));
        expect(new Set(controls).size).toBe(2);
        controls.forEach(id =>
            expect(document.getElementById(id)).toHaveAttribute('role', 'listbox')
        );
        const described = inputs.map(input => input.getAttribute('aria-describedby'));
        expect(new Set(described).size).toBe(2);
    });

    it('still filters and adds array suggestions', () => {
        const onItemsChange = vi.fn();
        render(
            <TagInput
                items={[]}
                suggestions={['logo', 'background']}
                onItemsChange={onItemsChange}
            />
        );
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'back' } });
        fireEvent.click(screen.getByRole('option', { name: 'background' }));

        expect(onItemsChange).toHaveBeenCalledWith(['background']);
    });

    it('points aria-controls at the listbox only while it is rendered', () => {
        render(<TagInput items={[]} suggestions={['logo']} />);
        const input = screen.getByRole('combobox');
        expect(input).not.toHaveAttribute('aria-controls');

        fireEvent.focus(input);
        expect(document.getElementById(input.getAttribute('aria-controls'))).toHaveAttribute(
            'role',
            'listbox'
        );

        fireEvent.keyDown(input, { key: 'Escape' });
        expect(input).not.toHaveAttribute('aria-controls');
    });
});

describe('TagInputField', () => {
    it('names the input by its field label and describes it by the field text', () => {
        render(
            <TagInputField
                field={{ key: 'asset_types', label: 'Asset Types', description: 'Which types' }}
                value={[]}
                onChange={() => {}}
            />
        );
        const input = screen.getByRole('combobox', { name: 'Asset Types' });

        expect(input).toHaveAttribute('id', 'field-asset_types');
        expect(input).toHaveAccessibleDescription(/Which types/);
    });
});
