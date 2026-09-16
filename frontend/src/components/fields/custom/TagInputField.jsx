/** Form wrapper for TagInput: tag_input edits, tag_display is read-only; both read field config. */

import React, { useCallback } from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription } from '../primitives';
import { TagInput } from '../features/tag/TagInput';

export const TagInputField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        // Handle both string and array values gracefully
        const normalizedValue = React.useMemo(() => {
            if (Array.isArray(value)) return value;
            if (typeof value === 'string') {
                // Handle comma-separated string values
                return value
                    ? value
                          .split(',')
                          .map(item => item.trim())
                          .filter(Boolean)
                    : [];
            }
            return [];
        }, [value]);

        // Standard onChange handler following field patterns
        const handleItemsChange = useCallback(
            newItems => {
                onChange(newItems);
            },
            [onChange]
        );

        // Field ID generation following test-ui patterns
        const inputId = `field-${field.key}`;

        // Determine field behavior based on type and disabled state
        const isTagDisplay = field.type === 'tag_display';
        const isDisplayMode = disabled || field.disabled || isTagDisplay;

        // Map field configuration to TagInput props
        const tagInputProps = {
            items: normalizedValue,
            onItemsChange: handleItemsChange,
            suggestions: field.suggestions || [],
            allowCustom: field.allowCustom ?? true,
            placeholder: field.placeholder || 'Add item...',
            disabled: isDisplayMode,
            maxItems: field.maxItems,
            caseSensitive: field.caseSensitive ?? false,

            // Validation function from field config
            validateItem: field.validateItem,

            // Custom filter function from field config
            filterFunction: field.filterFunction,

            // Badge configuration with field-type specific colors
            badgeProps: {
                variant: isTagDisplay ? 'accent' : 'interactive',
                size: 'medium',
                ...field.badgeProps, // Allow field-level badge customization
            },

            // Accessibility labels
            addLabel: field.addLabel || `Add ${field.itemType || 'item'}`,
            removeLabel: field.removeLabel || `Remove ${field.itemType || 'item'}`,

            // ARIA integration with field primitives
            'aria-describedby': `${inputId}-desc ${inputId}-error`.trim(),
            'aria-invalid': highlightInvalid,
            'aria-labelledby': `${inputId}-label`,
        };

        return (
            <FieldWrapper invalid={highlightInvalid}>
                <FieldLabel
                    htmlFor={inputId}
                    id={`${inputId}-label`}
                    label={field.label}
                    required={field.required}
                />

                <TagInput
                    {...tagInputProps}
                    // Additional props for proper form integration
                    id={inputId}
                    name={field.key}
                />

                <FieldDescription id={`${inputId}-desc`} description={field.description} />
                <FieldError id={`${inputId}-error`} message={errorMessage} />
            </FieldWrapper>
        );
    }
);

TagInputField.displayName = 'TagInputField';

export default TagInputField;
