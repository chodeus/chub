import React, { useCallback } from 'react';
import { FieldRow, InputBase } from '../primitives';
import { useOptionalFormField } from '../../forms/FormContext';

export const TextField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        // Optional FormContext integration - returns null if not in FormProvider
        const formField = useOptionalFormField(field.key);

        // Use FormContext if available, otherwise use props
        const finalValue = formField?.value ?? value;
        const finalOnChange = formField?.onChange ?? onChange;
        const finalHighlightInvalid = formField?.highlightInvalid ?? highlightInvalid;
        const finalErrorMessage = formField?.errorMessage ?? errorMessage;
        const finalOnBlur = formField?.onBlur;

        const handleChange = useCallback(
            e => {
                finalOnChange(e.target.value);
            },
            [finalOnChange]
        );

        const inputId = field.id || `field-${field.key}`;

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                helpText={field.helpText}
                description={field.description}
                error={finalErrorMessage}
                invalid={finalHighlightInvalid}
            >
                <InputBase
                    id={inputId}
                    type="text"
                    name={field.key}
                    value={finalValue || ''}
                    placeholder={field.placeholder}
                    disabled={disabled}
                    required={field.required}
                    maxLength={field.maxLength}
                    minLength={field.minLength}
                    pattern={field.pattern}
                    onChange={handleChange}
                    onBlur={finalOnBlur}
                    invalid={finalHighlightInvalid}
                    aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                    aria-invalid={finalHighlightInvalid}
                />
            </FieldRow>
        );
    }
);

TextField.displayName = 'TextField';

export default TextField;
