/** Guards the placeholder list: derived from the registry table, not from what has rendered. */
import { FieldRegistry } from './FieldRegistry.jsx';

describe('FieldRegistry', () => {
    it('lists the placeholder types before any field has rendered', () => {
        expect(FieldRegistry.getPlaceholderFieldTypes().sort()).toEqual([
            'media_display',
            'media_info_display',
            'poster',
        ]);
    });

    it('counts dir_picker as implemented', () => {
        expect(FieldRegistry.isWorkingFieldType('dir_picker')).toBe(true);
    });

    it('counts a registered extension type as implemented, not a placeholder', () => {
        FieldRegistry.register('test_only_extension_field', () => null);

        expect(FieldRegistry.isWorkingFieldType('test_only_extension_field')).toBe(true);
        expect(FieldRegistry.getPlaceholderFieldTypes()).not.toContain('test_only_extension_field');
    });
});
