/**
 * NumberField Component
 *
 * Clean number input (no ± stepper buttons — those aren't in the mocks).
 * Accepts typed digits/decimal/minus with min/max bounds.
 */

import React, { useCallback } from 'react';
import { FieldRow, InputBase } from '../primitives';
import { useOptionalFormField } from '../../forms/FormContext';

export const NumberField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
        onBlur,
    }) => {
        // Optional FormContext integration
        const formField = useOptionalFormField(field.key);

        // Use FormContext if available, otherwise use props
        const finalValue = formField?.value ?? value;
        const finalOnChange = formField?.onChange ?? onChange;
        const finalHighlightInvalid = formField?.highlightInvalid ?? highlightInvalid;
        const finalErrorMessage = formField?.errorMessage ?? errorMessage;
        const finalOnBlur = formField?.onBlur ?? onBlur;
        const numValue = finalValue !== null && finalValue !== undefined ? Number(finalValue) : 0;
        const min = field.min !== undefined ? Number(field.min) : undefined;
        const max = field.max !== undefined ? Number(field.max) : undefined;

        const handleInputChange = useCallback(
            e => {
                const inputValue = e.target.value;

                // Allow empty string, digits, decimal point, and minus sign
                if (inputValue === '' || /^-?\d*\.?\d*$/.test(inputValue)) {
                    // If it's a valid number, convert and validate bounds
                    if (inputValue !== '' && !isNaN(inputValue)) {
                        const newValue = Number(inputValue);
                        if (min !== undefined && newValue < min) return;
                        if (max !== undefined && newValue > max) return;
                        finalOnChange(newValue);
                    } else if (inputValue === '') {
                        finalOnChange(null);
                    } else {
                        // Allow partial input (like "-" or "1." while typing)
                        finalOnChange(inputValue);
                    }
                }
            },
            [min, max, finalOnChange]
        );

        const inputId = field.id || `field-${field.key}`;

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                description={field.description}
                error={finalErrorMessage}
                invalid={finalHighlightInvalid}
            >
                <InputBase
                    id={inputId}
                    type="text"
                    inputMode="numeric"
                    name={field.key}
                    value={typeof finalValue === 'string' ? finalValue : numValue || ''}
                    onChange={handleInputChange}
                    onBlur={finalOnBlur}
                    disabled={disabled}
                    required={field.required}
                    placeholder={field.placeholder}
                    invalid={finalHighlightInvalid}
                    className="w-full sm:max-w-[200px] sm:ml-auto"
                    aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                    aria-invalid={finalHighlightInvalid}
                />
            </FieldRow>
        );
    }
);

NumberField.displayName = 'NumberField';
