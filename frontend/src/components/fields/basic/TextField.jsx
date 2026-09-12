import React, { useCallback } from 'react';
import { FieldRow, InputBase } from '../primitives';

export const TextField = React.memo(
    ({
        field,
        value,
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        const handleChange = useCallback(
            e => {
                onChange(e.target.value);
            },
            [onChange]
        );

        const inputId = field.id || `field-${field.key}`;

        return (
            <FieldRow
                htmlFor={inputId}
                label={field.label}
                required={field.required}
                helpText={field.helpText}
                description={field.description}
                error={errorMessage}
                invalid={highlightInvalid}
            >
                <InputBase
                    id={inputId}
                    type="text"
                    name={field.key}
                    value={value}
                    placeholder={field.placeholder}
                    disabled={disabled}
                    required={field.required}
                    maxLength={field.maxLength}
                    minLength={field.minLength}
                    pattern={field.pattern}
                    onChange={handleChange}
                    invalid={highlightInvalid}
                    aria-describedby={`${field.descId || `${inputId}-desc`} ${field.errorId || `${inputId}-error`}`.trim()}
                    aria-invalid={highlightInvalid}
                />
            </FieldRow>
        );
    }
);

TextField.displayName = 'TextField';

export default TextField;
